from __future__ import annotations

import os
import sqlite3
from functools import wraps
from pathlib import Path

from flask import Flask, flash, g, redirect, render_template, request, session, url_for

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "database.db"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "aquilon-dev-secret-change-me")
app.config["ADMIN_LOGIN"] = os.environ.get("ADMIN_LOGIN", "admin")
app.config["ADMIN_PASSWORD"] = os.environ.get("ADMIN_PASSWORD", "aquilon123")


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


def init_db() -> None:
    db = sqlite3.connect(DATABASE)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS launches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            apartment_number TEXT NOT NULL,
            glass TEXT NOT NULL,
            floor TEXT NOT NULL,
            ceiling TEXT NOT NULL,
            additional TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    db.commit()
    db.close()


@app.teardown_appcontext
def close_db(exception: Exception | None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not session.get("admin_logged_in"):
            flash("Сначала войдите в админ-панель.", "warning")
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapped_view


@app.route("/")
def home():
    if session.get("admin_logged_in"):
        return redirect(url_for("object_dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        login_value = request.form.get("login", "").strip()
        password_value = request.form.get("password", "").strip()

        if (
            login_value == app.config["ADMIN_LOGIN"]
            and password_value == app.config["ADMIN_PASSWORD"]
        ):
            session["admin_logged_in"] = True
            flash("Вход выполнен успешно.", "success")
            return redirect(url_for("object_dashboard"))

        flash("Неверный логин или пароль.", "error")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    session.clear()
    flash("Вы вышли из системы.", "info")
    return redirect(url_for("login"))


@app.route("/objects/kvartal-100-7")
@login_required
def object_dashboard():
    db = get_db()
    records = db.execute(
        """
        SELECT id, apartment_number, glass, floor, ceiling, additional, created_at
        FROM launches
        ORDER BY id DESC
        """
    ).fetchall()
    return render_template(
        "object_dashboard.html",
        object_name="Квартал 100-7",
        records=records,
    )


@app.route("/objects/kvartal-100-7/add", methods=["POST"])
@login_required
def add_record():
    apartment_number = request.form.get("apartment_number", "").strip()
    glass = request.form.get("glass", "").strip()
    floor_value = request.form.get("floor", "").strip()
    ceiling = request.form.get("ceiling", "").strip()
    additional = request.form.get("additional", "").strip()

    if not apartment_number or not glass or not floor_value or not ceiling:
        flash("Заполните обязательные поля: номер квартиры, стекла, пол, потолок.", "error")
        return redirect(url_for("object_dashboard"))

    db = get_db()
    db.execute(
        """
        INSERT INTO launches (apartment_number, glass, floor, ceiling, additional)
        VALUES (?, ?, ?, ?, ?)
        """,
        (apartment_number, glass, floor_value, ceiling, additional),
    )
    db.commit()

    flash("Запись добавлена в таблицу запуска объекта.", "success")
    return redirect(url_for("object_dashboard"))


@app.route("/objects/kvartal-100-7/delete/<int:record_id>", methods=["POST"])
@login_required
def delete_record(record_id: int):
    db = get_db()
    db.execute("DELETE FROM launches WHERE id = ?", (record_id,))
    db.commit()
    flash("Запись удалена.", "info")
    return redirect(url_for("object_dashboard"))


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
