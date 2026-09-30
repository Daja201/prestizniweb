# Provides the study-resource catalogue, uploads, votes, downloads, and author deletion.
from __future__ import annotations

import io
import re
import unicodedata
from pathlib import PurePosixPath
from urllib.parse import quote as url_quote, urlencode, urlsplit
from zipfile import BadZipFile, ZipFile

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import and_, desc, func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import require_user
from app.core.flash import flash
from app.core.ratelimit import rate_limit
from app.core.storage import abs_path, delete as delete_storage, save_bytes
from app.core.templates import render
from app.models import ClassMember, Resource, ResourceVote, SchoolClass, Tag, User, resource_tags

router = APIRouter()

SUBJECTS = [
    "Matematika",
    "Český jazyk",
    "Anglický jazyk",
    "Programování",
    "Elektrotechnika",
    "Počítačové sítě",
    "Operační systémy",
    "Databáze",
    "Webové aplikace",
    "Fyzika",
    "Ostatní",
]
KINDS = {
    "notes": "Poznámky",
    "test": "Test",
    "exercises": "Cvičení",
    "link": "Odkaz",
    "other": "Ostatní",
}
ALLOWED_EXTENSIONS = {
    "pdf",
    "docx",
    "doc",
    "pptx",
    "ppt",
    "xlsx",
    "xls",
    "odt",
    "ods",
    "odp",
    "txt",
    "md",
    "png",
    "jpg",
    "webp",
}
MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "ppt": "application/vnd.ms-powerpoint",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "odt": "application/vnd.oasis.opendocument.text",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "odp": "application/vnd.oasis.opendocument.presentation",
    "txt": "text/plain",
    "md": "text/markdown",
    "png": "image/png",
    "jpg": "image/jpeg",
    "webp": "image/webp",
}


class UploadValidationError(ValueError):
    """Raised when an uploaded resource does not match its claimed format."""


def _parse_tags(raw: str) -> list[str]:
    values = re.split(r"[,\n;]+", raw)
    tags: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(value.strip().split()).lower()
        if not normalized:
            continue
        if len(normalized) > 30:
            raise UploadValidationError("Každý štítek může mít nejvýše 30 znaků.")
        if normalized not in seen:
            tags.append(normalized)
            seen.add(normalized)
    if len(tags) > 5:
        raise UploadValidationError("Lze přidat nejvýše 5 štítků.")
    return tags


def _sanitize_file_name(name: str | None, extension: str) -> str:
    raw = unicodedata.normalize("NFKC", name or "soubor")
    raw = raw.replace("\\", "/")
    raw = PurePosixPath(raw).name
    raw = "".join(ch for ch in raw if ch.isprintable() and ord(ch) not in {0x202E, 0x202D, 0x202C, 0x2066, 0x2067, 0x2068, 0x2069})
    raw = re.sub(r"\s+", " ", raw).strip(" .")
    stem = PurePosixPath(raw).stem or "soubor"
    stem = re.sub(r"[^\w .()\-]", "_", stem, flags=re.UNICODE).strip(" .") or "soubor"
    max_stem = max(1, 200 - len(extension) - 1)
    return f"{stem[:max_stem]}.{extension}"


def _looks_like_html_or_script(data: bytes) -> bool:
    head = data[:65536]
    text = head.decode("utf-8", errors="ignore").lstrip("\ufeff \t\r\n").lower()
    return (
        text.startswith("<!doctype html")
        or text.startswith("<html")
        or text.startswith("<svg")
        or "<script" in text
        or "javascript:" in text
    )


def _is_zip_of_expected_type(data: bytes, extension: str) -> bool:
    if not data.startswith(b"PK"):
        return False
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            if len(names) > 2000:
                return False
            if ".." in " ".join(names):
                return False
            if extension == "docx":
                return "[Content_Types].xml" in names and any(name.startswith("word/") for name in names)
            if extension == "xlsx":
                return "[Content_Types].xml" in names and any(name.startswith("xl/") for name in names)
            if extension == "pptx":
                return "[Content_Types].xml" in names and any(name.startswith("ppt/") for name in names)
            if extension in {"odt", "ods", "odp"}:
                if "mimetype" not in names:
                    return False
                expected = {
                    "odt": b"application/vnd.oasis.opendocument.text",
                    "ods": b"application/vnd.oasis.opendocument.spreadsheet",
                    "odp": b"application/vnd.oasis.opendocument.presentation",
                }[extension]
                return archive.read("mimetype").strip() == expected
    except (BadZipFile, KeyError, RuntimeError):
        return False
    return False


def _sniff_upload(data: bytes, extension: str) -> None:
    if not data:
        raise UploadValidationError("Soubor je prázdný.")
    if extension == "pdf" and data.startswith(b"%PDF"):
        return
    if extension == "png" and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return
    if extension == "jpg" and data.startswith(b"\xff\xd8\xff"):
        return
    if extension == "webp" and len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return
    if extension in {"docx", "pptx", "xlsx", "odt", "ods", "odp"} and _is_zip_of_expected_type(data, extension):
        return
    if extension in {"doc", "ppt", "xls"} and data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return
    if extension in {"txt", "md"}:
        if data.startswith(b"PK") or b"\x00" in data:
            raise UploadValidationError("Textový soubor obsahuje nepovolená binární data.")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UploadValidationError("Textový soubor musí být v UTF-8.") from exc
        if _looks_like_html_or_script(data):
            raise UploadValidationError("HTML, SVG a skripty nejsou povolené.")
        return
    raise UploadValidationError("Obsah souboru neodpovídá zvolené příponě.")


def _validate_url(value: str) -> str:
    clean = value.strip()
    if len(clean) > 500:
        raise ValueError("Odkaz může mít nejvýše 500 znaků.")
    parsed = urlsplit(clean)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Povolené jsou pouze odkazy http:// nebo https://.")
    if any(ord(ch) < 32 for ch in clean):
        raise ValueError("Odkaz obsahuje nepovolené znaky.")
    return clean


def _url_domain(value: str | None) -> str | None:
    if not value:
        return None
    return urlsplit(value).hostname


def _valid_class_for_user(db: Session, class_id: int, user_id: int) -> SchoolClass | None:
    return db.scalar(
        select(SchoolClass)
        .join(ClassMember, ClassMember.class_id == SchoolClass.id)
        .where(
            SchoolClass.id == class_id,
            SchoolClass.status == "active",
            ClassMember.user_id == user_id,
            ClassMember.status == "approved",
        )
    )


def _resource_visible_to(user: User, resource: Resource) -> bool:
    if resource.status == "deleted":
        return False
    if resource.status == "visible":
        return True
    return user.role in {"moderator", "admin"} and resource.status == "hidden"


def _resource_base_query(user: User):
    visibility = Resource.status == "visible"
    if user.role in {"moderator", "admin"}:
        visibility = Resource.status.in_(["visible", "hidden"])
    return (
        select(Resource)
        .options(selectinload(Resource.author), selectinload(Resource.tags), selectinload(Resource.school_class))
        .where(visibility)
    )


def _resource_filters(stmt, subject: str | None, year: int | None, kind: str | None, class_slug: str | None, tag: str | None):
    if subject:
        stmt = stmt.where(Resource.subject == subject)
    if year is not None:
        stmt = stmt.where(Resource.school_year == year)
    if kind:
        stmt = stmt.where(Resource.kind == kind)
    if class_slug:
        stmt = stmt.join(Resource.school_class).where(
            and_(SchoolClass.slug == class_slug, SchoolClass.status == "active")
        )
    if tag:
        tag_exists = (
            select(resource_tags.c.resource_id)
            .join(Tag, Tag.id == resource_tags.c.tag_id)
            .where(
                resource_tags.c.resource_id == Resource.id,
                Tag.name == tag.lower(),
            )
        )
        stmt = stmt.where(tag_exists.exists())
    return stmt


def _resource_search(stmt, query: str | None):
    if not query:
        return stmt, None
    clean = query.strip()
    tsq = func.websearch_to_tsquery("simple", clean)
    text_match = Resource.search_vector.op("@@")(tsq)
    title_match = func.unaccent(Resource.title).ilike(func.unaccent(_search_pattern(clean)), escape="\\")
    stmt = stmt.where(or_(text_match, title_match))
    rank = func.ts_rank(Resource.search_vector, tsq) + func.similarity(func.unaccent(Resource.title), func.unaccent(clean))
    return stmt, rank


def _search_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _load_resource_filters(db: Session) -> dict[str, object]:
    classes = list(
        db.scalars(
            select(SchoolClass).where(SchoolClass.status == "active").order_by(SchoolClass.name.asc())
        ).all()
    )
    tags = list(db.scalars(select(Tag).order_by(Tag.name.asc()).limit(200)).all())
    return {"classes": classes, "available_tags": tags}


def _load_resource_form_data(db: Session, user: User) -> dict[str, object]:
    classes = list(
        db.scalars(
            select(SchoolClass)
            .join(ClassMember, ClassMember.class_id == SchoolClass.id)
            .where(
                SchoolClass.status == "active",
                ClassMember.user_id == user.id,
                ClassMember.status == "approved",
            )
            .order_by(SchoolClass.name.asc())
        ).all()
    )
    return {"classes": classes}


def _resource_query_url(
    page: int,
    subject: str | None,
    year: int | None,
    kind: str | None,
    class_slug: str | None,
    tag: str | None,
    query: str | None,
    sort: str,
) -> str:
    params: list[tuple[str, str]] = [("page", str(page))]
    for key, value in (
        ("subject", subject),
        ("year", str(year) if year is not None else None),
        ("kind", kind),
        ("class", class_slug),
        ("tag", tag),
        ("q", query),
    ):
        if value:
            params.append((key, value))
    if sort != "new":
        params.append(("sort", sort))
    return "/resources?" + urlencode(params)


def _sync_tags(db: Session, names: list[str]) -> list[Tag]:
    result: list[Tag] = []
    for name in names:
        tag = db.scalar(select(Tag).where(Tag.name == name))
        if tag is None:
            tag = Tag(name=name)
            db.add(tag)
            db.flush()
        result.append(tag)
    return result


@router.get("/resources", response_class=HTMLResponse)
def list_resources(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    page: int = Query(1, ge=1),
    subject: str | None = Query(None, max_length=40),
    year: int | None = Query(None, ge=1, le=4),
    kind: str | None = Query(None, max_length=10),
    class_filter: str | None = Query(None, alias="class", max_length=40),
    tag: str | None = Query(None, max_length=30),
    q: str | None = Query(None, max_length=100),
    sort: str = Query("new", pattern="^(new|top)$"),
):
    subject = subject.strip() if subject else None
    class_filter = class_filter.strip() if class_filter else None
    tag = tag.strip().lower() if tag else None
    q = q.strip() if q else None
    if subject not in {None, *SUBJECTS}:
        subject = None
    if kind not in {None, *KINDS}:
        kind = None

    stmt = _resource_base_query(user)
    stmt = _resource_filters(stmt, subject, year, kind, class_filter, tag)
    stmt, rank = _resource_search(stmt, q)
    if q and rank is not None:
        stmt = stmt.order_by(desc(rank), desc(Resource.id))
    elif sort == "top":
        stmt = stmt.order_by(desc(Resource.upvotes_count), desc(Resource.downloads_count), desc(Resource.id))
    else:
        stmt = stmt.order_by(desc(Resource.id))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    resources = list(db.scalars(stmt.offset((page - 1) * 24).limit(24)).all())
    has_next = page * 24 < total
    next_page = page + 1 if has_next else None
    next_url = (
        _resource_query_url(next_page, subject, year, kind, class_filter, tag, q, sort)
        if next_page
        else None
    )
    voted_ids = {
        resource_id
        for resource_id in db.scalars(
            select(ResourceVote.resource_id).where(
                ResourceVote.user_id == user.id,
                ResourceVote.resource_id.in_([resource.id for resource in resources]),
            )
        ).all()
    } if resources else set()

    context = {
        "resources": resources,
        "subject": subject or "",
        "year": year,
        "kind": kind or "",
        "class_slug": class_filter or "",
        "tag": tag or "",
        "q": q or "",
        "sort": sort,
        "next_url": next_url,
        "page": page,
        "total": total,
        "voted_ids": voted_ids,
        "subjects": SUBJECTS,
        "kinds": KINDS,
        **_load_resource_filters(db),
    }
    if request.headers.get("HX-Request") == "true":
        context["fragment"] = True
        return render(request, "resources/_items.html", **context)
    context["fragment"] = False
    return render(request, "resources/list.html", **context)


@router.get("/resources/new", response_class=HTMLResponse)
def new_resource(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    return render(
        request,
        "resources/new.html",
        subjects=SUBJECTS,
        kinds=KINDS,
        form={},
        errors={},
        **_load_resource_form_data(db, user),
    )


@router.post("/resources", response_class=HTMLResponse, dependencies=[Depends(rate_limit("resource-create", 10, 3600))])
def create_resource(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    subject: str = Form(...),
    school_year: str = Form(""),
    kind: str = Form(...),
    tags: str = Form(""),
    class_id: str = Form(""),
    url: str = Form(""),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    form = {
        "title": title,
        "description": description,
        "subject": subject,
        "school_year": school_year,
        "kind": kind,
        "tags": tags,
        "class_id": class_id,
        "url": url,
        "file_name": file.filename if file else "",
    }
    errors: dict[str, str] = {}
    clean_title = title.strip()
    clean_description = description.strip()
    if not 3 <= len(clean_title) <= 120:
        errors["title"] = "Název musí mít 3 až 120 znaků."
    if len(clean_description) > 1000:
        errors["description"] = "Popis může mít nejvýše 1000 znaků."
    if subject not in SUBJECTS:
        errors["subject"] = "Vyberte platný předmět."
    if kind not in KINDS:
        errors["kind"] = "Vyberte platný typ materiálu."

    parsed_year: int | None = None
    if school_year.strip():
        try:
            parsed_year = int(school_year)
        except ValueError:
            errors["school_year"] = "Ročník musí být číslo 1 až 4."
        else:
            if parsed_year not in range(1, 5):
                errors["school_year"] = "Ročník musí být 1 až 4."

    parsed_class_id: int | None = None
    if class_id.strip():
        try:
            parsed_class_id = int(class_id)
        except ValueError:
            errors["class_id"] = "Vyberte platnou třídu."
        else:
            if parsed_class_id <= 0 or _valid_class_for_user(db, parsed_class_id, user.id) is None:
                errors["class_id"] = "Třída musí být aktivní a musíte být schváleným členem."

    try:
        tag_names = _parse_tags(tags)
    except UploadValidationError as exc:
        tag_names = []
        errors["tags"] = str(exc)

    clean_url = url.strip()
    has_url = bool(clean_url)
    has_file = file is not None and bool(file.filename)
    if has_url == has_file:
        errors["source"] = "Přidejte právě jeden odkaz nebo soubor."

    file_data: bytes | None = None
    file_extension: str | None = None
    clean_file_name: str | None = None
    if has_file and file is not None:
        original_name = file.filename or "soubor"
        suffix = PurePosixPath(original_name).suffix.lower().lstrip(".")
        if suffix not in ALLOWED_EXTENSIONS:
            errors["file"] = "Tento typ souboru není povolený."
        else:
            max_bytes = settings.max_resource_mb * 1024 * 1024
            file_data = file.file.read(max_bytes + 1)
            if len(file_data) > max_bytes:
                errors["file"] = f"Soubor může mít nejvýše {settings.max_resource_mb} MB."
            else:
                try:
                    _sniff_upload(file_data, suffix)
                except UploadValidationError as exc:
                    errors["file"] = str(exc)
                else:
                    file_extension = suffix
                    clean_file_name = _sanitize_file_name(original_name, suffix)

    if has_url:
        try:
            clean_url = _validate_url(clean_url)
        except ValueError as exc:
            errors["url"] = str(exc)

    if errors:
        return render(
            request,
            "resources/new.html",
            422,
            subjects=SUBJECTS,
            kinds=KINDS,
            form=form,
            errors=errors,
            **_load_resource_form_data(db, user),
        )

    resource = Resource(
        author_id=user.id,
        class_id=parsed_class_id,
        title=clean_title,
        description=clean_description,
        subject=subject,
        school_year=parsed_year,
        kind=kind,
        url=clean_url if has_url else None,
        file_path=None,
        file_name=None,
        file_size=None,
        file_mime=None,
        status="visible",
    )
    db.add(resource)
    db.flush()

    if has_file and file_data is not None and file_extension and clean_file_name:
        relative_path = save_bytes("resources", file_data, file_extension)
        resource.file_path = relative_path
        resource.file_name = clean_file_name
        resource.file_size = len(file_data)
        resource.file_mime = MEDIA_TYPES[file_extension]

    resource_tags = _sync_tags(db, tag_names)
    resource.tags = resource_tags
    db.commit()

    response = RedirectResponse(f"/resources/{resource.id}", status_code=303)
    flash(response, "Studijní materiál byl přidán.", "success")
    return response


@router.get("/resources/{resource_id}", response_class=HTMLResponse)
def resource_detail(
    request: Request,
    resource_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    resource = db.scalar(
        select(Resource)
        .options(selectinload(Resource.author), selectinload(Resource.tags), selectinload(Resource.school_class))
        .where(Resource.id == resource_id)
    )
    if resource is None or not _resource_visible_to(user, resource):
        return render(request, "errors/404.html", status_code=404)
    voted = db.scalar(
        select(ResourceVote.resource_id).where(
            ResourceVote.resource_id == resource.id,
            ResourceVote.user_id == user.id,
        )
    ) is not None
    extension = resource.file_name.rsplit(".", 1)[1].lower() if resource.file_name and "." in resource.file_name else None
    return render(
        request,
        "resources/detail.html",
        resource=resource,
        voted=voted,
        resource_domain=_url_domain(resource.url),
        file_extension=extension,
        kind_label=KINDS.get(resource.kind, resource.kind),
    )


@router.get("/resources/{resource_id}/download")
def download_resource(
    request: Request,
    resource_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    resource = db.scalar(select(Resource).where(Resource.id == resource_id))
    if resource is None or not _resource_visible_to(user, resource) or not resource.file_path:
        return render(request, "errors/404.html", status_code=404)
    path = abs_path(resource.file_path)
    if not path.is_file():
        return render(request, "errors/404.html", status_code=404)

    extension = resource.file_name.rsplit(".", 1)[1].lower() if resource.file_name and "." in resource.file_name else "bin"
    media_type = MEDIA_TYPES.get(extension, "application/octet-stream")
    db.execute(
        update(Resource)
        .where(Resource.id == resource.id)
        .values(downloads_count=Resource.downloads_count + 1)
    )
    db.commit()

    response = FileResponse(path, media_type=media_type)
    file_name = resource.file_name or path.name
    response.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{url_quote(file_name, safe='')}"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@router.post("/resources/{resource_id}/vote", response_class=HTMLResponse, dependencies=[Depends(rate_limit("resource-vote", 120, 60))])
def vote_resource(
    request: Request,
    resource_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    resource = db.scalar(select(Resource).where(Resource.id == resource_id, Resource.status == "visible"))
    if resource is None:
        return render(request, "errors/404.html", status_code=404)
    existing = db.scalar(
        select(ResourceVote).where(
            ResourceVote.resource_id == resource.id,
            ResourceVote.user_id == user.id,
        )
    )
    if existing:
        db.delete(existing)
        db.execute(
            update(Resource)
            .where(Resource.id == resource.id)
            .values(upvotes_count=func.greatest(Resource.upvotes_count - 1, 0))
        )
        voted = False
    else:
        db.add(ResourceVote(resource_id=resource.id, user_id=user.id))
        db.execute(
            update(Resource)
            .where(Resource.id == resource.id)
            .values(upvotes_count=Resource.upvotes_count + 1)
        )
        voted = True
    db.commit()
    db.refresh(resource)
    return render(request, "resources/_vote_button.html", resource=resource, user=user, voted=voted)


@router.post("/resources/{resource_id}/delete")
def delete_resource(
    resource_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    resource = db.scalar(select(Resource).where(Resource.id == resource_id))
    if resource is None or resource.status == "deleted":
        response = RedirectResponse("/resources", status_code=303)
        flash(response, "Materiál nebyl nalezen.", "error")
        return response
    if resource.author_id != user.id:
        response = RedirectResponse(f"/resources/{resource.id}", status_code=303)
        flash(response, "Tento materiál můžete odstranit jen vy.", "error")
        return response

    old_path = resource.file_path
    resource.status = "deleted"
    db.commit()
    delete_storage(old_path)
    response = RedirectResponse("/resources", status_code=303)
    flash(response, "Materiál byl odstraněn.", "success")
    return response