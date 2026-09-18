from pathlib import Path
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "nadree api"))

from app.main import create_app
from app.config import Settings
from app import responses
from packaging.requirements import Requirement


def main():
    app = create_app(Settings(_env_file=None, env="development", database_url="", redis_url="", jwt_secret=""))
    openapi = app.openapi()
    models = {1: responses.SignedIn, 2: responses.Tokens, 3: responses.Status, 4: responses.SpotResult,
              5: responses.ProfileResult, 6: responses.Status, 7: responses.Status, 17: responses.PrimaryResult,
              23: responses.ShopResult, 28: responses.Hierarchy, 29: responses.CreatedSpot, 30: responses.Admins,
              31: responses.Status, 32: responses.Applicants, 33: responses.Status}
    master = (root / "rental-project-master.md").read_text(encoding="utf-8")
    pins = (root / "nadree api/requirements.lock").read_text(encoding="utf-8").splitlines()
    for line in pins:
        assert str(Requirement(line).specifier).startswith("==")
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(root / "나드리고 api 마무리.xlsx") as workbook:
        assert workbook.testzip() is None
        tree = ET.fromstring(workbook.read("xl/worksheets/sheet31.xml"))
        cells = {cell.get("r"): "".join(node.text or "" for node in cell.iter(ns + "t")) for cell in tree.iter(ns + "c")}
        for number, model in models.items():
            start = master.index(f'<a id="api-{number:02d}"></a>')
            section = master[start:master.index("</details>", start)]
            url = re.search(r"\| 요청 URL \| (.*?) \|", section)[1]
            method = re.search(r"\| Method \| (.*?) \|", section)[1].lower()
            assert method in openapi["paths"][url.removeprefix("DefaultURL")]
            value = json.loads(re.search(r"\*\*응답 예시\*\*\n\n```json\n(.*?)\n```", section, re.S)[1])
            model.model_validate(value)
            url_cell = next(ref for ref, text in cells.items() if text == url)
            row = int(re.search(r"\d+", url_cell)[0])
            assert json.loads(cells["J" + str(row + 6)]) == value, number
    assert len(re.findall(r'<a id="api-\d+"></a>', master)) == 38
    print(f"Verified: {len(models)} W01/W02 routes, methods and response examples match MD/Excel; {len(pins)} dependency pins.")


if __name__ == "__main__":
    main()
