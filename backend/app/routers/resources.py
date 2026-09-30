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
from sqlalchemy import and_, delete, desc, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
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
    "English Language",
    "Chemistry and Ecology",
    "History",
    "Physics",
    "Office Applications",
    "Mathematics",
    "Math Exercises",
    "Mechatronics",
    "Operating Systems",
    "Computer Graphics",
    "Programming",
    "Network Technologies",
    "Computer Hardware",
    "Physical Education",
    "Web Applications",
    "Czech Language and Literature",
    "Other",
]

KINDS = {
    "notes": "Notes",
    "test": "Test",
    "exercises": "Exercises",
    "link": "Odkaz",
    "other": "Other",
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
            raise UploadValidationError("Each tag can be at most 30 characters.")
        if normalized not in seen:
            tags.append(normalized)
            seen.add(normalized)
    if len(tags) > 5:
        raise UploadValidationError("Up to 5 tags allowed.")
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
        raise UploadValidationError("File is empty.")
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
            raise UploadValidationError("Text file contains disallowed binary data.")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UploadValidationError("Text file must be UTF-8 encoded.") from exc
        if _looks_like_html_or_script(data):
            raise UploadValidationError("HTML, SVG and scripts are not allowed.")
        return
    raise UploadValidationError("File content does not match its extension.")


def _validate_url(value: str) -> str:
    clean = value.strip()
    if len(clean) > 500:
        raise ValueError("URL can be at most 500 characters.")
    parsed = urlsplit(clean)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Only http:// or https:// links are allowed.")
    if any(ord(ch) < 32 for ch in clean):
        raise ValueError("URL contains invalid characters.")
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
    return user.role in {"admin", "super_admin"} and resource.status == "hidden"


def _resource_base_query(user: User):
    visibility = Resource.status == "visible"
    if user.role in {"admin", "super_admin"}:
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
    files: list[UploadFile] = File(default=[]),
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
        "file_name": files[0].filename if files else "",
    }
    errors: dict[str, str] = {}
    clean_title = title.strip()
    clean_description = description.strip()
    if not 3 <= len(clean_title) <= 120:
        errors["title"] = "Title must be 3 to 120 characters."
    if len(clean_description) > 1000:
        errors["description"] = "Description can be at most 1000 characters."
    if subject not in SUBJECTS:
        errors["subject"] = "Please select a valid subject."
    if kind not in KINDS:
        errors["kind"] = "Please select a valid type."

    parsed_year: int | None = None
    if school_year.strip():
        try:
            parsed_year = int(school_year)
        except ValueError:
            errors["school_year"] = "Year must be a number 1–4."
        else:
            if parsed_year not in range(1, 5):
                errors["school_year"] = "Year must be 1–4."

    parsed_class_id: int | None = None
    if class_id.strip():
        try:
            parsed_class_id = int(class_id)
        except ValueError:
            errors["class_id"] = "Please select a valid class."
        else:
            if parsed_class_id <= 0 or _valid_class_for_user(db, parsed_class_id, user.id) is None:
                errors["class_id"] = "Class must be active and you must be an approved member."

    try:
        tag_names = _parse_tags(tags)
    except UploadValidationError as exc:
        tag_names = []
        errors["tags"] = str(exc)

    clean_url = url.strip()
    has_url = bool(clean_url)
    valid_files = [f for f in files if f and f.filename]
    has_file = bool(valid_files)
    if not has_url and not has_file:
        errors["source"] = "Please provide a URL or upload at least one file."
    if has_url and has_file:
        errors["source"] = "Please provide either a URL or files, not both."

    # Validate first file for single-resource URL path; multi-file handled below
    file_data: bytes | None = None
    file_extension: str | None = None
    clean_file_name: str | None = None
    if has_file and not has_url and valid_files:
        first_file = valid_files[0]
        original_name = first_file.filename or "file"
        suffix = PurePosixPath(original_name).suffix.lower().lstrip(".")
        if suffix not in ALLOWED_EXTENSIONS:
            errors["file"] = f"File type '.{suffix}' is not allowed."
        else:
            max_bytes = settings.max_resource_mb * 1024 * 1024
            file_data = first_file.file.read(max_bytes + 1)
            if len(file_data) > max_bytes:
                errors["file"] = f"File can be at most {settings.max_resource_mb} MB."
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

    last_resource_id: int | None = None
    created_count = 0

    # If URL, create a single resource
    if has_url:
        resource = Resource(
            author_id=user.id,
            class_id=parsed_class_id,
            title=clean_title,
            description=clean_description,
            subject=subject,
            school_year=parsed_year,
            kind=kind,
            url=clean_url,
            file_path=None,
            file_name=None,
            file_size=None,
            file_mime=None,
            status="visible",
        )
        db.add(resource)
        db.flush()
        resource.tags = _sync_tags(db, tag_names)
        db.commit()
        last_resource_id = resource.id
        created_count = 1
    else:
        # Multiple file upload: create one resource per file
        for upload_file in valid_files:
            orig_name = upload_file.filename or "file"
            suffix = PurePosixPath(orig_name).suffix.lower().lstrip(".")
            if suffix not in ALLOWED_EXTENSIONS:
                continue
            max_bytes = settings.max_resource_mb * 1024 * 1024
            data = upload_file.file.read(max_bytes + 1)
            if len(data) > max_bytes:
                continue
            try:
                _sniff_upload(data, suffix)
            except UploadValidationError:
                continue
            safe_name = _sanitize_file_name(orig_name, suffix)
            relative_path = save_bytes("resources", data, suffix)
            resource = Resource(
                author_id=user.id,
                class_id=parsed_class_id,
                title=clean_title if len(valid_files) == 1 else f"{clean_title} — {safe_name}",
                description=clean_description,
                subject=subject,
                school_year=parsed_year,
                kind=kind,
                url=None,
                file_path=relative_path,
                file_name=safe_name,
                file_size=len(data),
                file_mime=MEDIA_TYPES.get(suffix, "application/octet-stream"),
                status="visible",
            )
            db.add(resource)
            db.flush()
            resource.tags = _sync_tags(db, tag_names)
            db.commit()
            last_resource_id = resource.id
            created_count += 1

    if created_count == 0:
        errors["source"] = "No valid files could be processed."
        return render(request, "resources/new.html", 422, subjects=SUBJECTS, kinds=KINDS, form=form, errors=errors, **_load_resource_form_data(db, user))

    redirect_to = f"/resources/{last_resource_id}" if created_count == 1 else "/resources"
    response = RedirectResponse(redirect_to, status_code=303)
    flash(response, f"{created_count} material(s) uploaded.", "success")
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
    removed_id = db.scalar(
        delete(ResourceVote)
        .where(ResourceVote.resource_id == resource.id, ResourceVote.user_id == user.id)
        .returning(ResourceVote.resource_id)
    )
    if removed_id is not None:
        db.execute(
            update(Resource)
            .where(Resource.id == resource.id)
            .values(upvotes_count=func.greatest(Resource.upvotes_count - 1, 0))
        )
        voted = False
    else:
        inserted_id = db.scalar(
            pg_insert(ResourceVote)
            .values(resource_id=resource.id, user_id=user.id)
            .on_conflict_do_nothing(index_elements=[ResourceVote.resource_id, ResourceVote.user_id])
            .returning(ResourceVote.resource_id)
        )
        if inserted_id is not None:
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
        flash(response, "Material not found.", "error")
        return response
    if resource.author_id != user.id:
        response = RedirectResponse(f"/resources/{resource.id}", status_code=303)
        flash(response, "You can only delete your own materials.", "error")
        return response

    old_path = resource.file_path
    resource.status = "deleted"
    db.commit()
    delete_storage(old_path)
    response = RedirectResponse("/resources", status_code=303)
    flash(response, "Material deleted.", "success")
    return response