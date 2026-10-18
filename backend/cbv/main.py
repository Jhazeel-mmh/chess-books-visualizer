"""HTTP API used by the frontend (run with ``uvicorn cbv.main:app``)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, UploadFile
from pydantic import BaseModel
from fastapi.responses import FileResponse, PlainTextResponse, Response

from . import library

@asynccontextmanager
async def lifespan(_app: FastAPI):
    library.resume_unfinished()
    yield


app = FastAPI(title="Chess Books Visualizer", lifespan=lifespan)


def _found(fn, *args):
    try:
        return fn(*args)
    except library.NotFound:
        raise HTTPException(status_code=404)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/books")
def list_books() -> list[dict]:
    return library.list_books()


@app.post("/api/books")
async def upload_book(file: UploadFile) -> dict:
    return library.import_book(file.filename or "book", await file.read())


@app.get("/api/books/{book_id}")
def get_book(book_id: str) -> dict:
    return _found(library.get_book, book_id)


@app.delete("/api/books/{book_id}", status_code=204)
def delete_book(book_id: str) -> None:
    _found(library.delete_book, book_id)


@app.post("/api/books/{book_id}/analyze", status_code=202)
def reanalyze(book_id: str) -> dict:
    _found(library.start_analysis, book_id)
    return library.get_book(book_id)


@app.get("/api/books/{book_id}/analysis")
def get_analysis(book_id: str) -> dict:
    return _found(library.analysis, book_id)


@app.get("/api/books/{book_id}/layout")
def get_layout(book_id: str) -> dict:
    return _found(library.layout, book_id)


@app.get("/api/books/{book_id}/pages/{page}.png")
def get_page_image(book_id: str, page: int, zoom: float = Query(2.0, ge=0.5, le=4.0)) -> FileResponse:
    # Rounded so that the cache does not fill up with near-identical renders.
    path = _found(library.page_image, book_id, page, round(zoom * 2) / 2)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "max-age=86400"})


@app.get("/api/books/{book_id}/pages/{page}/marks")
def get_page_marks(book_id: str, page: int) -> list:
    return _found(library.page_marks, book_id, page)


@app.get("/api/books/{book_id}/epub/{path:path}")
def get_epub_file(book_id: str, path: str) -> Response:
    data, media_type = _found(library.epub_file, book_id, path)
    # Book files come from outside: never let them run scripts in the app's origin.
    return Response(data, media_type=media_type, headers={"Content-Security-Policy": "script-src 'none'"})


class DiagramFix(BaseModel):
    key: str
    placement: str
    turn: str | None = None


@app.put("/api/books/{book_id}/diagrams", status_code=202)
def correct_diagram(book_id: str, fix: DiagramFix) -> dict:
    if fix.turn not in (None, "w", "b"):
        raise HTTPException(status_code=422, detail="turn must be w or b")
    try:
        return _found(library.correct_diagram, book_id, fix.key, fix.placement, fix.turn)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.get("/api/books/{book_id}/move-fixes")
def get_move_fixes(book_id: str) -> list:
    return _found(library.move_fixes, book_id)


@app.put("/api/books/{book_id}/move-fixes", status_code=202)
def put_move_fixes(book_id: str, fixes: list[dict]) -> dict:
    try:
        return _found(library.save_move_fixes, book_id, fixes)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.get("/api/books/{book_id}/user/{name}")
def get_user_data(book_id: str, name: str) -> dict:
    if name not in library.USER_DATA:
        raise HTTPException(status_code=404)
    return _found(library.user_data, book_id, name)


@app.put("/api/books/{book_id}/user/{name}", status_code=204)
def put_user_data(book_id: str, name: str, data: dict) -> Response:
    try:
        _found(library.save_user_data, book_id, name, data)
    except ValueError as e:
        raise HTTPException(status_code=413, detail=str(e))
    return Response(status_code=204)


@app.get("/api/trainer")
def get_trainer() -> dict:
    return library.trainer_record()


@app.put("/api/trainer", status_code=204)
def put_trainer(record: dict) -> None:
    try:
        library.save_trainer_record(record)
    except ValueError as e:
        raise HTTPException(status_code=413, detail=str(e))


@app.get("/api/trainer/books")
def get_trainer_books() -> list:
    return library.trainer_books()


@app.post("/api/trainer/session")
def new_trainer_session(test: bool = False) -> dict:
    return library.trainer_session(test=test)


@app.get("/api/books/{book_id}/games/{game_id}.pgn", response_class=PlainTextResponse)
def get_pgn(book_id: str, game_id: str) -> str:
    return _found(library.game_pgn, book_id, game_id)
