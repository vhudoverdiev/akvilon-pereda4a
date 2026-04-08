from __future__ import annotations

import json
import os
import sqlite3
from ipaddress import ip_address
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from flask import Flask, flash, g, redirect, render_template, request, session, url_for

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "database.db"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "aquilon-dev-secret-change-me")
app.config["ADMIN_LOGIN"] = os.environ.get("ADMIN_LOGIN", "admin")
app.config["ADMIN_PASSWORD"] = os.environ.get("ADMIN_PASSWORD", "aquilon123")

DEFAULT_TABS = [
    {
        "slug": "podgotovitelnyy-etap",
        "name": "Подготовительный этап",
        "columns": [
            "№ квартиры",
            "Вид отделки",
            "Стены",
            "Пол",
            "Потолок",
            "Стекла",
            "Доп",
            "Регулировка входной двери",
            "Показ (0 = нет, 1 = да)",
            "Причина не ПО",
        ],
    },
    {
        "slug": "ne-prodannye-kvartiry",
        "name": "Не проданные квартиры",
        "columns": [
            "№ квартиры",
            "Статус",
            "Ответственный",
            "Комментарий",
            "Дата",
        ],
    },
    {
        "slug": "raskhod-stroitelnogo-materiala",
        "name": "Расход строительного материала",
        "columns": [
            "№ квартиры",
            "Вид работ",
            "Дата",
            "Кол-во работников",
            "Кол-во смен",
            "Пена монтажная (низ)",
            "Пена монтажная (огнеупорная)",
        ],
    },
    {
        "slug": "vydacha-otstupnogo-materiala",
        "name": "Выдача отступного материала",
        "columns": ["№ квартиры", "Ветонит", "Плитонит", "Ротбанд", "Дата"],
    },
    {
        "slug": "zakaz-materialov",
        "name": "Заказ материалов",
        "columns": ["Наименование материала", "Вид работ", "Количество", "Вид"],
    },
]


def _is_ip_host(host: str) -> bool:
    host_name = host.split(":", 1)[0].strip("[]")
    if not host_name:
        return False
    try:
        ip_address(host_name)
        return True
    except ValueError:
        return False


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


def init_db() -> None:
    db = sqlite3.connect(DATABASE)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS objects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS tab_definitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            object_id INTEGER NOT NULL,
            tab_slug TEXT NOT NULL,
            tab_name TEXT NOT NULL,
            columns_json TEXT NOT NULL,
            sort_order INTEGER NOT NULL,
            FOREIGN KEY (object_id) REFERENCES objects(id) ON DELETE CASCADE,
            UNIQUE (object_id, tab_slug)
        );

        CREATE TABLE IF NOT EXISTS tab_rows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tab_id INTEGER NOT NULL,
            values_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (tab_id) REFERENCES tab_definitions(id) ON DELETE CASCADE
        );
        """
    )
    db.commit()

    exists = db.execute("SELECT id FROM objects LIMIT 1").fetchone()
    if not exists:
        db.execute("INSERT INTO objects (name) VALUES (?)", ("Квартал 100-7",))
        object_id = db.execute("SELECT id FROM objects WHERE name = ?", ("Квартал 100-7",)).fetchone()[0]
        for i, tab in enumerate(DEFAULT_TABS):
            db.execute(
                """
                INSERT INTO tab_definitions (object_id, tab_slug, tab_name, columns_json, sort_order)
                VALUES (?, ?, ?, ?, ?)
                """,
                (object_id, tab["slug"], tab["name"], json.dumps(tab["columns"], ensure_ascii=False), i),
            )
        db.commit()

    db.close()


@app.teardown_appcontext
def close_db(exception: Exception | None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.after_request
def keep_ip_host_redirects(response):
    """
    If a redirect target was generated with a canonical domain, but the user
    came via direct IP, keep redirects on the same IP host.
    """
    location = response.headers.get("Location")
    if not location:
        return response

    request_host = request.host
    if not _is_ip_host(request_host):
        return response

    target = urlsplit(location)
    if not target.netloc:
        return response

    response.headers["Location"] = urlunsplit(
        (target.scheme or request.scheme, request_host, target.path, target.query, target.fragment)
    )
    return response


def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not session.get("admin_logged_in"):
            flash("Сначала войдите в админ-панель.", "warning")
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapped_view


def ensure_default_tabs(db: sqlite3.Connection, object_id: int) -> None:
    count = db.execute(
        "SELECT COUNT(*) as total FROM tab_definitions WHERE object_id = ?", (object_id,)
    ).fetchone()["total"]
    if count:
        return

    for i, tab in enumerate(DEFAULT_TABS):
        db.execute(
            """
            INSERT INTO tab_definitions (object_id, tab_slug, tab_name, columns_json, sort_order)
            VALUES (?, ?, ?, ?, ?)
            """,
            (object_id, tab["slug"], tab["name"], json.dumps(tab["columns"], ensure_ascii=False), i),
        )
    db.commit()


@app.route("/")
def home():
    if session.get("admin_logged_in"):
        return redirect(url_for("objects_page"))
    return render_template("login.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("admin_logged_in"):
        return redirect(url_for("objects_page"))

    if request.method == "POST":
        login_value = request.form.get("login", "").strip()
        password_value = request.form.get("password", "").strip()

        if (
            login_value == app.config["ADMIN_LOGIN"]
            and password_value == app.config["ADMIN_PASSWORD"]
        ):
            session["admin_logged_in"] = True
            flash("Вход выполнен успешно.", "success")
            return redirect(url_for("objects_page"))

        flash("Неверный логин или пароль.", "error")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    session.clear()
    flash("Вы вышли из системы.", "info")
    return redirect(url_for("login"))


@app.route("/objects")
@login_required
def objects_page():
    db = get_db()
    objects = db.execute("SELECT id, name, created_at FROM objects ORDER BY id DESC").fetchall()
    return render_template("objects.html", objects=objects)


@app.route("/objects/add", methods=["POST"])
@login_required
def add_object():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Введите название объекта.", "error")
        return redirect(url_for("objects_page"))

    db = get_db()
    try:
        cursor = db.execute("INSERT INTO objects (name) VALUES (?)", (name,))
        object_id = cursor.lastrowid
        for i, tab in enumerate(DEFAULT_TABS):
            db.execute(
                """
                INSERT INTO tab_definitions (object_id, tab_slug, tab_name, columns_json, sort_order)
                VALUES (?, ?, ?, ?, ?)
                """,
                (object_id, tab["slug"], tab["name"], json.dumps(tab["columns"], ensure_ascii=False), i),
            )
        db.commit()
        flash("Объект добавлен.", "success")
    except sqlite3.IntegrityError:
        flash("Объект с таким названием уже существует.", "error")

    return redirect(url_for("objects_page"))


@app.route("/objects/<int:object_id>")
@login_required
def object_dashboard(object_id: int):
    db = get_db()
    obj = db.execute("SELECT id, name FROM objects WHERE id = ?", (object_id,)).fetchone()
    if not obj:
        flash("Объект не найден.", "error")
        return redirect(url_for("objects_page"))

    ensure_default_tabs(db, object_id)
    tabs_raw = db.execute(
        """
        SELECT id, tab_slug, tab_name, columns_json
        FROM tab_definitions
        WHERE object_id = ?
        ORDER BY sort_order, id
        """,
        (object_id,),
    ).fetchall()

    tabs = []
    for tab in tabs_raw:
        columns = json.loads(tab["columns_json"])
        rows_raw = db.execute(
            "SELECT id, values_json, created_at FROM tab_rows WHERE tab_id = ? ORDER BY id DESC",
            (tab["id"],),
        ).fetchall()
        rows = []
        for row in rows_raw:
            rows.append({"id": row["id"], "values": json.loads(row["values_json"]), "created_at": row["created_at"]})
        tabs.append(
            {
                "id": tab["id"],
                "slug": tab["tab_slug"],
                "name": tab["tab_name"],
                "columns": columns,
                "rows": rows,
            }
        )

    active_tab = request.args.get("tab", tabs[0]["slug"] if tabs else None)
    if tabs and active_tab not in [tab["slug"] for tab in tabs]:
        active_tab = tabs[0]["slug"]

    return render_template("object_dashboard.html", object_item=obj, tabs=tabs, active_tab=active_tab)


@app.route("/objects/<int:object_id>/tabs/<int:tab_id>/add", methods=["POST"])
@login_required
def add_tab_row(object_id: int, tab_id: int):
    db = get_db()
    tab = db.execute(
        "SELECT id, tab_slug, columns_json FROM tab_definitions WHERE id = ? AND object_id = ?",
        (tab_id, object_id),
    ).fetchone()
    if not tab:
        flash("Вкладка не найдена.", "error")
        return redirect(url_for("object_dashboard", object_id=object_id))

    columns = json.loads(tab["columns_json"])
    values = {}
    has_data = False
    for col in columns:
        field_name = f"col::{col}"
        value = request.form.get(field_name, "").strip()
        values[col] = value
        if value:
            has_data = True

    if not has_data:
        flash("Заполните хотя бы одно поле.", "error")
        return redirect(url_for("object_dashboard", object_id=object_id, tab=tab["tab_slug"]))

    db.execute(
        "INSERT INTO tab_rows (tab_id, values_json) VALUES (?, ?)",
        (tab_id, json.dumps(values, ensure_ascii=False)),
    )
    db.commit()
    flash("Запись добавлена.", "success")
    return redirect(url_for("object_dashboard", object_id=object_id, tab=tab["tab_slug"]))


@app.route("/objects/<int:object_id>/tabs/<int:tab_id>/rows/<int:row_id>/delete", methods=["POST"])
@login_required
def delete_tab_row(object_id: int, tab_id: int, row_id: int):
    db = get_db()
    tab = db.execute(
        "SELECT tab_slug FROM tab_definitions WHERE id = ? AND object_id = ?", (tab_id, object_id)
    ).fetchone()
    if not tab:
        flash("Вкладка не найдена.", "error")
        return redirect(url_for("object_dashboard", object_id=object_id))

    db.execute("DELETE FROM tab_rows WHERE id = ? AND tab_id = ?", (row_id, tab_id))
    db.commit()
    flash("Запись удалена.", "info")
    return redirect(url_for("object_dashboard", object_id=object_id, tab=tab["tab_slug"]))


with app.app_context():
    init_db()


if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "5000")),
        debug=debug_mode,
    )
