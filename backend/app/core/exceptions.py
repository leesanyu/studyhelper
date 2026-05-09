# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class StudyHelperError(Exception):
    def __init__(self, message: str, status_code: int = 500, code: str = "internal_error") -> None:
        self.message = message
        self.status_code = status_code
        self.code = code


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StudyHelperError)
    async def studyhelper_error_handler(
        _request: Request, exc: StudyHelperError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )
