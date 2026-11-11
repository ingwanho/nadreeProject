from pathlib import Path
import json
import posixpath
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
              31: responses.Status, 32: responses.Applicants, 33: responses.Status,
              39: responses.AdminSignupResult}
    master = (root / "rental-project-master.md").read_text(encoding="utf-8")
    pins = (root / "nadree api/requirements.lock").read_text(encoding="utf-8").splitlines()
    for line in pins:
        assert str(Requirement(line).specifier).startswith("==")
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(root / "나드리고 api 마무리.xlsx") as workbook:
        assert workbook.testzip() is None
        document = ET.fromstring(workbook.read("xl/workbook.xml"))
        relations = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
        sheet = next(s for s in document.iter(ns + "sheet") if s.get("name") == "전체 API 명세")
        relation_id = sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = next(r.get("Target") for r in relations if r.get("Id") == relation_id)
        sheet_path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
        tree = ET.fromstring(workbook.read(sheet_path))
        cells = {cell.get("r"): "".join(node.text or "" for node in cell.iter(ns + "t")) for cell in tree.iter(ns + "c")}
        seen = set()
        sections = list(re.finditer(r'<a id="api-(\d+)"></a>', master))
        for anchor in sections:
            number = int(anchor[1])
            start = anchor.start()
            section = master[start:master.index("</details>", start)]
            url = re.search(r"\| 요청 URL \| (.*?) \|", section)[1]
            method = re.search(r"\| Method \| (.*?) \|", section)[1].lower()
            assert method in openapi["paths"][url.removeprefix("DefaultURL")]
            key = (method, url.removeprefix("DefaultURL"))
            assert key not in seen, key
            seen.add(key)
            candidates = [int(re.search(r"\d+", ref)[0]) for ref, value in cells.items()
                          if ref.startswith("B") and value == url]
            row = next(r for r in candidates if cells.get("B" + str(r + 1), "").lower() == method)
            example = re.search(r"\*\*응답 예시\*\*\n\n```json\n(.*?)\n```", section, re.S)
            if example:
                value = json.loads(example[1])
                if number in models:
                    models[number].model_validate(value)
                assert json.loads(cells["J" + str(row + 6)]) == value, number
        expected = {(method, path) for path, operations in openapi["paths"].items()
                    for method in operations if method in {"get", "post", "put", "patch", "delete"}}
        assert seen == expected, (expected - seen, seen - expected)
        assert len(sections) == len(expected)
    print(f"Verified: {len(seen)} API methods match MD/Excel/OpenAPI; {len(models)} typed W01/W02 examples; {len(pins)} dependency pins.")


if __name__ == "__main__":
    main()
