from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError


class Problem(Exception):
    def __init__(self, status: int, code: str):
        self.status = status
        self.code = code


def install_handlers(app: FastAPI):
    def response(status, code):
        return JSONResponse({"status": "fail", "errorCode": code}, status_code=status,
                            headers={"Cache-Control": "no-store"})

    @app.exception_handler(Problem)
    async def problem_handler(request: Request, error: Problem):
        return response(error.status, error.code)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, error: RequestValidationError):
        # Pydantic errors can contain submitted passwords and tokens.
        return response(422, "INVALID_INPUT")

    @app.exception_handler(IntegrityError)
    async def conflict(request: Request, error: IntegrityError):
        return response(409, "DATA_CONFLICT")

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, error: SQLAlchemyError):
        return response(503, "DATABASE_UNAVAILABLE")
