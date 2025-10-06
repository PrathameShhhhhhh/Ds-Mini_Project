"""
main.py - Student DB Management
Features added:
 - Edit student details
 - Delete student records
 - Branch statistics (per-division counts, remaining seats)
 - Export to CSV and PDF (PDF via reportlab if installed)
 - Search student (name / PRN / class_roll)
 - Student password update and view profile
 - SQLite persistence (migrates existing JSON data if present)
 - Input validation
"""

import os
import json
import sqlite3
import hashlib
import uuid
import csv
from typing import Dict, List, Optional
from datetime import datetime

# Optional PDF export
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

# Constants
DATA_DIR = "db_data"
JSON_STUDENTS = os.path.join(DATA_DIR, "students.json")
JSON_TEACHERS = os.path.join(DATA_DIR, "teachers.json")
META_JSON = os.path.join(DATA_DIR, "meta.json")
SQLITE_FILE = os.path.join(DATA_DIR, "students.db")

COLLEGE_DOMAIN = "college.edu"
MAX_PER_DIVISION = 70
DIVISIONS = ["1", "2", "3"]

# Utilities
def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)

def hash_password(password: str, salt: Optional[str] = None) -> Dict[str,str]:
    if salt is None:
        salt = uuid.uuid4().hex
    pw_hash = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return {"salt": salt, "pw_hash": pw_hash}

def verify_password(password: str, salt: str, pw_hash: str) -> bool:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest() == pw_hash

def validate_nonempty(s: str, name: str):
    if not s or not s.strip():
        raise ValueError(f"{name} cannot be empty.")
    return s.strip()

def branch_code(branch: str) -> str:
    b = branch.strip().upper()
    # take first two letters, pad if needed
    code = (b[:2]).upper()
    if len(code) < 2:
        code = (code + "X")[:2]
    return code

# -------------------------
# SQLite persistence layer
# -------------------------
class Storage:
    def __init__(self, path=SQLITE_FILE):
        ensure_data_dir()
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        # migrate JSON if present and DB empty
        if self._is_empty() and (os.path.exists(JSON_STUDENTS) or os.path.exists(JSON_TEACHERS)):
            self._migrate_from_json()

    def _init_schema(self):
        cur = self.conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            prn TEXT PRIMARY KEY,
            class_roll TEXT UNIQUE,
            username TEXT UNIQUE,
            salt TEXT,
            pw_hash TEXT,
            first_name TEXT,
            last_name TEXT,
            branch TEXT,
            division TEXT,
            email TEXT,
            extra TEXT
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS teachers (
            username TEXT PRIMARY KEY,
            salt TEXT,
            pw_hash TEXT,
            name TEXT,
            branch TEXT
        );
        """)
        # ensure meta next_prn
        cur.execute("SELECT value FROM meta WHERE key = 'next_prn'")
        r = cur.fetchone()
        if not r:
            # default start
            cur.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('next_prn', ?)", ("1001",))
        self.conn.commit()

    def _is_empty(self) -> bool:
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) as c FROM students")
        return cur.fetchone()["c"] == 0

    def _migrate_from_json(self):
        print("Migrating JSON data into SQLite (if JSON files found)...")
        cur = self.conn.cursor()
        # students
        try:
            with open(JSON_STUDENTS, "r", encoding="utf-8") as f:
                students = json.load(f)
            for s in students:
                cur.execute("""
                    INSERT OR IGNORE INTO students (prn, class_roll, username, salt, pw_hash, first_name, last_name, branch, division, email, extra)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    s.get("prn"),
                    s.get("class_roll"),
                    s.get("username"),
                    s.get("salt"),
                    s.get("pw_hash"),
                    s.get("first_name"),
                    s.get("last_name"),
                    s.get("branch"),
                    s.get("division"),
                    s.get("email"),
                    json.dumps(s.get("extra", {}))
                ))
        except Exception:
            pass
        # teachers
        try:
            with open(JSON_TEACHERS, "r", encoding="utf-8") as f:
                teachers = json.load(f)
            for t in teachers:
                cur.execute("""
                    INSERT OR IGNORE INTO teachers (username, salt, pw_hash, name, branch)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    t.get("username"),
                    t.get("salt"),
                    t.get("pw_hash"),
                    t.get("name"),
                    t.get("branch")
                ))
        except Exception:
            pass
        # meta
        try:
            with open(META_JSON, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("next_prn"):
                cur.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('next_prn', ?)", (str(meta["next_prn"]),))
        except Exception:
            pass
        self.conn.commit()
        print("Migration (attempt) complete. If you had JSON files, their data should be in the DB now.")

    # meta
    def get_next_prn(self) -> str:
        cur = self.conn.cursor()
        cur.execute("SELECT value FROM meta WHERE key='next_prn'")
        v = int(cur.fetchone()["value"])
        cur.execute("UPDATE meta SET value = ? WHERE key = 'next_prn'", (str(v + 1),))
        self.conn.commit()
        return str(v)

    # student CRUD
    def insert_student(self, s: Dict):
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO students (prn, class_roll, username, salt, pw_hash, first_name, last_name, branch, division, email, extra)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            s["prn"], s.get("class_roll"), s["username"], s["salt"], s["pw_hash"],
            s["first_name"], s["last_name"], s["branch"], s["division"], s["email"], json.dumps(s.get("extra", {}))
        ))
        self.conn.commit()

    def update_student(self, prn: str, updates: Dict):
        cur = self.conn.cursor()
        columns = []
        values = []
        for k, v in updates.items():
            if k == "extra":
                v = json.dumps(v)
            columns.append(f"{k} = ?")
            values.append(v)
        values.append(prn)
        sql = f"UPDATE students SET {', '.join(columns)} WHERE prn = ?"
        cur.execute(sql, tuple(values))
        self.conn.commit()

    def delete_student(self, prn: str):
        cur = self.conn.cursor()
        cur.execute("DELETE FROM students WHERE prn = ?", (prn,))
        self.conn.commit()

    def find_student_by_prn(self, prn: str) -> Optional[Dict]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM students WHERE prn = ?", (prn,))
        r = cur.fetchone()
        return dict(r) if r else None

    def find_student_by_username(self, username: str) -> Optional[Dict]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM students WHERE username = ?", (username,))
        r = cur.fetchone()
        return dict(r) if r else None

    def find_student_by_class_roll(self, class_roll: str) -> Optional[Dict]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM students WHERE class_roll = ?", (class_roll,))
        r = cur.fetchone()
        return dict(r) if r else None

    def search_students_by_name(self, name_fragment: str) -> List[Dict]:
        cur = self.conn.cursor()
        like = f"%{name_fragment}%"
        cur.execute("SELECT * FROM students WHERE first_name LIKE ? OR last_name LIKE ?", (like, like))
        return [dict(r) for r in cur.fetchall()]

    def list_students_by_branch(self, branch: str) -> List[Dict]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM students WHERE branch = ? ORDER BY division, class_roll", (branch.upper(),))
        return [dict(r) for r in cur.fetchall()]

    def count_by_branch_division(self, branch: str) -> Dict[str, int]:
        cur = self.conn.cursor()
        res = {d:0 for d in DIVISIONS}
        cur.execute("SELECT division, COUNT(*) as c FROM students WHERE branch = ? GROUP BY division", (branch.upper(),))
        for r in cur.fetchall():
            res[str(r["division"])] = int(r["c"])
        return res

    # teacher CRUD
    def insert_teacher(self, t: Dict):
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO teachers (username, salt, pw_hash, name, branch)
            VALUES (?, ?, ?, ?, ?)
        """, (t["username"], t["salt"], t["pw_hash"], t["name"], t["branch"]))
        self.conn.commit()

    def find_teacher(self, username: str) -> Optional[Dict]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM teachers WHERE username = ?", (username,))
        r = cur.fetchone()
        return dict(r) if r else None

# -------------------------
# Business logic wrappers
# -------------------------
class StudentDB:
    def __init__(self, storage: Storage):
        self.storage = storage

    def _generate_prn(self) -> str:
        return self.storage.get_next_prn()

    def _assign_division(self, branch: str) -> str:
        counts = self.storage.count_by_branch_division(branch)
        for d in DIVISIONS:
            if counts.get(d, 0) < MAX_PER_DIVISION:
                return d
        raise ValueError("All divisions for this branch are full (3x70 = 210 students).")

    def _generate_class_roll(self, branch: str, division: str) -> str:
        # count existing in that branch+division, next roll is +1
        counts = self.storage.count_by_branch_division(branch)
        current = counts.get(division, 0) + 1
        if current > MAX_PER_DIVISION:
            raise ValueError(f"Division {division} in {branch} already full.")
        return f"{branch_code(branch)}{division}{current:02d}"

    def _generate_email(self, first_name, last_name, prn, branch):
        uname = f"{first_name.lower()}.{last_name.lower()}.{prn}"
        return f"{uname}@{branch.lower()}.{COLLEGE_DOMAIN}"

    def register_student(self, username, password, first_name, last_name, branch, extra=None):
        username = validate_nonempty(username, "username").lower()
        # check uniqueness
        if self.storage.find_student_by_username(username):
            raise ValueError("Username already exists for a student.")
        prn = self._generate_prn()
        pw = hash_password(password)
        division = self._assign_division(branch)
        class_roll = self._generate_class_roll(branch, division)
        email = self._generate_email(first_name, last_name, prn, branch)
        student = {
            "prn": prn,
            "class_roll": class_roll,
            "username": username,
            "salt": pw["salt"],
            "pw_hash": pw["pw_hash"],
            "first_name": first_name.strip(),
            "last_name": last_name.strip(),
            "branch": branch.strip().upper(),
            "division": division,
            "email": email,
            "extra": extra or {}
        }
        self.storage.insert_student(student)
        return student

    def student_login(self, username: str, password: str) -> Optional[Dict]:
        username = username.strip().lower()
        s = self.storage.find_student_by_username(username)
        if s and verify_password(password, s["salt"], s["pw_hash"]):
            # sanitize
            s.pop("pw_hash", None)
            s.pop("salt", None)
            # parse extra
            s["extra"] = json.loads(s.get("extra") or "{}") if isinstance(s.get("extra"), str) else s.get("extra", {})
            return s
        return None

    def teacher_register(self, username, password, name, branch):
        username = validate_nonempty(username, "username").lower()
        if self.storage.find_teacher(username):
            raise ValueError("Teacher username already exists.")
        pw = hash_password(password)
        t = {"username": username, "salt": pw["salt"], "pw_hash": pw["pw_hash"], "name": name.strip(), "branch": branch.strip().upper()}
        self.storage.insert_teacher(t)
        t = self.storage.find_teacher(username)
        t.pop("salt", None); t.pop("pw_hash", None)
        return t

    def teacher_login(self, username, password):
        t = self.storage.find_teacher(username.strip().lower())
        if t and verify_password(password, t["salt"], t["pw_hash"]):
            t.pop("salt", None); t.pop("pw_hash", None)
            return t
        return None

    # Edit student - only allowed fields unless admin (we don't implement roles beyond teacher/branch)
    def edit_student(self, prn: str, updates: Dict, editor_branch: Optional[str] = None):
        s = self.storage.find_student_by_prn(prn)
        if not s:
            raise ValueError("Student not found.")
        # permission: if editor_branch provided, ensure same branch
        if editor_branch and s["branch"].upper() != editor_branch.upper():
            raise PermissionError("You can only edit students of your branch.")
        allowed = {"first_name", "last_name", "email", "extra", "branch"}
        # note: changing branch should reassign division & class_roll carefully; we allow only updates that don't violate division limits
        applied = {}
        for k, v in updates.items():
            if k not in allowed:
                continue
            applied[k] = v
        if "branch" in applied:
            new_branch = applied["branch"].upper()
            # assign new division and class_roll for new branch
            new_div = self._assign_division(new_branch)
            new_roll = self._generate_class_roll(new_branch, new_div)
            applied["branch"] = new_branch
            applied["division"] = new_div
            applied["class_roll"] = new_roll
        # convert extra to json if dict
        if "extra" in applied and not isinstance(applied["extra"], str):
            applied["extra"] = json.dumps(applied["extra"])
        self.storage.update_student(prn, applied)
        return self.storage.find_student_by_prn(prn)

    def delete_student(self, prn: str, editor_branch: Optional[str] = None):
        s = self.storage.find_student_by_prn(prn)
        if not s:
            raise ValueError("Student not found.")
        if editor_branch and s["branch"].upper() != editor_branch.upper():
            raise PermissionError("You can only delete students of your branch.")
        self.storage.delete_student(prn)
        return True

    def branch_stats(self, branch: str) -> Dict[str, int]:
        counts = self.storage.count_by_branch_division(branch)
        total = sum(counts.values())
        remaining = {d: MAX_PER_DIVISION - counts.get(d, 0) for d in DIVISIONS}
        return {"total": total, "counts": counts, "remaining": remaining}

    def export_branch_csv(self, branch: str, path: str):
        students = self.storage.list_students_by_branch(branch)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["PRN", "Class Roll", "First Name", "Last Name", "Branch", "Division", "Email"])
            for s in students:
                writer.writerow([s["prn"], s.get("class_roll"), s["first_name"], s["last_name"], s["branch"], s["division"], s["email"]])
        return path

    def export_branch_pdf(self, branch: str, path: str):
        # requires reportlab; fallback to CSV raising an informative error
        if not REPORTLAB_AVAILABLE:
            raise RuntimeError("reportlab not installed. Install with `pip install reportlab` to enable PDF export.")
        students = self.storage.list_students_by_branch(branch)
        c = canvas.Canvas(path, pagesize=letter)
        width, height = letter
        title = f"Student List - {branch.upper()} - {datetime.now().strftime('%Y-%m-%d')}"
        c.setFont("Helvetica-Bold", 14)
        c.drawString(40, height - 50, title)
        c.setFont("Helvetica", 10)
        y = height - 80
        line_height = 14
        headers = ["PRN", "ClassRoll", "Name", "Division", "Email"]
        c.drawString(40, y, " | ".join(headers))
        y -= line_height
        for s in students:
            name = f"{s['first_name']} {s['last_name']}"
            row = f"{s['prn']} | {s.get('class_roll','')} | {name} | {s['division']} | {s['email']}"
            c.drawString(40, y, row[:200])  # trim long
            y -= line_height
            if y < 60:
                c.showPage()
                y = height - 40
        c.save()
        return path

    # Search helpers
    def search_by_name(self, fragment: str):
        return self.storage.search_students_by_name(fragment)

    def find_by_class_roll(self, class_roll: str):
        return self.storage.find_student_by_class_roll(class_roll)

    def get_student_profile(self, prn_or_class_roll: str):
        s = self.storage.find_student_by_prn(prn_or_class_roll) or self.storage.find_student_by_class_roll(prn_or_class_roll)
        if not s:
            return None
        s.pop("pw_hash", None); s.pop("salt", None)
        s["extra"] = json.loads(s.get("extra") or "{}") if isinstance(s.get("extra"), str) else s.get("extra", {})
        return s

    def change_student_password(self, username: str, old_password: str, new_password: str):
        s = self.storage.find_student_by_username(username.strip().lower())
        if not s:
            raise ValueError("Student not found.")
        if not verify_password(old_password, s["salt"], s["pw_hash"]):
            raise ValueError("Old password incorrect.")
        pw = hash_password(new_password)
        self.storage.update_student(s["prn"], {"salt": pw["salt"], "pw_hash": pw["pw_hash"]})
        return True

# -------------------------
# CLI
# -------------------------
def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def pause():
    input("Press Enter to continue...")

def main_menu(db: StudentDB):
    while True:
        clear_screen()
        print("\n\n~~~ Student DB Management ~~~")
        print("1) Student Register")
        print("2) Student Login")
        print("3) Teacher Register")
        print("4) Teacher Login")
        print("5) Branch Statistics")
        print("6) Export Branch (CSV/PDF)")
        print("7) Search Student")
        print("8) Admin: List all students")
        print("0) Exit")
        ch = input("Choose: ").strip()
        try:
            if ch == "1":
                student_register_flow(db)
            elif ch == "2":
                student_login_flow(db)
            elif ch == "3":
                teacher_register_flow(db)
            elif ch == "4":
                teacher_login_flow(db)
            elif ch == "5":
                branch_stats_flow(db)
            elif ch == "6":
                export_branch_flow(db)
            elif ch == "7":
                search_flow(db)
            elif ch == "8":
                admin_list_all(db)
            elif ch == "0":
                print("Goodbye.")
                break
            else:
                print("Invalid choice.")
        except Exception as e:
            print("Error:", e)
        pause()

# Flows
def student_register_flow(db: StudentDB):
    try:
        uname = validate_nonempty(input("Username: "), "username")
        pw = validate_nonempty(input("Password: "), "password")
        fn = validate_nonempty(input("First name: "), "first name")
        ln = validate_nonempty(input("Last name: "), "last name")
        branch = validate_nonempty(input("Branch (e.g. CSE): "), "branch")
        student = db.register_student(uname, pw, fn, ln, branch)
        print("Registered!")
        print("PRN:", student["prn"])
        print("Class Roll:", student["class_roll"])
        print("Email:", student["email"])
        print("Division:", student["division"])
    except Exception as e:
        print("Error:", e)

def student_login_flow(db: StudentDB):
    uname = input("Username: ").strip()
    pw = input("Password: ").strip()
    s = db.student_login(uname, pw)
    if not s:
        print("Invalid credentials.")
        return
    print(f"Welcome {s['first_name']} {s['last_name']}")
    while True:
        print("\nStudent Menu:")
        print("1) View profile")
        print("2) Change password")
        print("0) Logout")
        c = input("Choose: ").strip()
        if c == "1":
            profile = db.get_student_profile(s["prn"]) 
            print(json.dumps(profile, indent=2))
        elif c == "2":
            old = input("Old password: ")
            new = input("New password: ")
            try:
                db.change_student_password(uname, old, new)
                print("Password changed.")
            except Exception as e:
                print("Error:", e)
        elif c == "0":
            break
        else:
            print("Invalid choice.")

def teacher_register_flow(db: StudentDB):
    try:
        uname = validate_nonempty(input("Teacher username: "), "username")
        pw = validate_nonempty(input("Password: "), "password")
        name = validate_nonempty(input("Full name: "), "full name")
        branch = validate_nonempty(input("Branch (e.g. CSE): "), "branch")
        t = db.teacher_register(uname, pw, name, branch)
        print("Teacher registered:", t)
    except Exception as e:
        print("Error:", e)

def teacher_login_flow(db: StudentDB):
    uname = input("Teacher username: ").strip()
    pw = input("Password: ").strip()
    t = db.teacher_login(uname, pw)
    if not t:
        print("Invalid credentials.")
        return
    print(f"Welcome {t['name']} (Branch {t['branch']})")
    while True:
        print("\nTeacher Menu:")
        print("1) View students in your branch")
        print("2) View student by PRN or class roll")
        print("3) Edit student")
        print("4) Delete student")
        print("0) Logout")
        c = input("Choose: ").strip()
        try:
            if c == "1":
                students = db.storage.list_students_by_branch(t["branch"])
                if not students:
                    print("No students.")
                else:
                    for s in students:
                        print(f"{s['prn']} | {s.get('class_roll')} | {s['first_name']} {s['last_name']} | Div {s['division']} | {s['email']}")
            elif c == "2":
                key = input("Enter PRN or Class Roll: ").strip()
                prof = db.get_student_profile(key)
                if prof and prof["branch"] == t["branch"]:
                    print(json.dumps(prof, indent=2))
                else:
                    print("Not found or not your branch.")
            elif c == "3":
                prn = input("Enter PRN of student to edit: ").strip()
                print("Enter new values (leave blank to skip):")
                fn = input("First name: ").strip()
                ln = input("Last name: ").strip()
                email = input("Email: ").strip()
                branch_new = input("Change branch to (e.g. CSE) or blank: ").strip()
                extra_raw = input("Extra JSON (e.g. {\"phone\":\"123\"}): ").strip()
                updates = {}
                if fn: updates["first_name"] = fn
                if ln: updates["last_name"] = ln
                if email: updates["email"] = email
                if branch_new: updates["branch"] = branch_new
                if extra_raw:
                    try:
                        updates["extra"] = json.loads(extra_raw)
                    except Exception:
                        print("Invalid JSON for extra; skipping.")
                updated = db.edit_student(prn, updates, editor_branch=t["branch"])
                print("Updated:", {k: updated[k] for k in ("prn","class_roll","first_name","last_name","branch","division","email")})
            elif c == "4":
                prn = input("Enter PRN to delete: ").strip()
                confirm = input("Type DELETE to confirm: ").strip()
                if confirm == "DELETE":
                    db.delete_student(prn, editor_branch=t["branch"])
                    print("Deleted.")
                else:
                    print("Cancelled.")
            elif c == "0":
                break
            else:
                print("Invalid option.")
        except Exception as e:
            print("Error:", e)

def branch_stats_flow(db: StudentDB):
    branch = input("Enter branch (e.g. CSE): ").strip()
    stats = db.branch_stats(branch)
    print("Branch:", branch.upper())
    print("Total students:", stats["total"])
    print("Per-division counts:")
    for d in DIVISIONS:
        print(f"  Division {d}: {stats['counts'].get(d,0)} students, remaining seats {stats['remaining'].get(d,0)}")

def export_branch_flow(db: StudentDB):
    branch = input("Branch to export: ").strip()
    t = input("Format (csv/pdf): ").strip().lower()
    filename = f"{branch.upper()}_students_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    try:
        if t == "csv":
            path = os.path.join(DATA_DIR, f"{filename}.csv")
            db.export_branch_csv(branch, path)
            print("CSV saved to", path)
        elif t == "pdf":
            if not REPORTLAB_AVAILABLE:
                print("PDF export requires 'reportlab'. Install via `pip install reportlab`.")
                return
            path = os.path.join(DATA_DIR, f"{filename}.pdf")
            db.export_branch_pdf(branch, path)
            print("PDF saved to", path)
        else:
            print("Unknown format.")
    except Exception as e:
        print("Error:", e)

def search_flow(db: StudentDB):
    print("1) Search by name")
    print("2) Search by PRN")
    print("3) Search by class roll")
    ch = input("Choose: ").strip()
    if ch == "1":
        q = input("Name fragment: ").strip()
        res = db.search_by_name(q)
        if not res:
            print("No matches.")
        else:
            for s in res:
                print(f"{s['prn']} | {s.get('class_roll')} | {s['first_name']} {s['last_name']} | {s['branch']}")
    elif ch == "2":
        q = input("PRN: ").strip()
        r = db.get_student_profile(q)
        if r:
            print(json.dumps(r, indent=2))
        else:
            print("Not found.")
    elif ch == "3":
        q = input("Class roll: ").strip()
        r = db.get_student_profile(q)
        if r:
            print(json.dumps(r, indent=2))
        else:
            print("Not found.")
    else:
        print("Invalid choice.")

def admin_list_all(db: StudentDB):
    cur = db.storage.conn.cursor()
    cur.execute("SELECT prn, class_roll, first_name, last_name, branch, division, email, username FROM students ORDER BY branch, division, class_roll")
    rows = cur.fetchall()
    for r in rows:
        print(f"{r['prn']} | {r['class_roll']} | {r['first_name']} {r['last_name']} | {r['branch']} | Div {r['division']} | {r['email']} | {r['username']}")

# Entry point
def main():
    storage = Storage(SQLITE_FILE)
    db = StudentDB(storage)
    main_menu(db)

if __name__ == "__main__":
    main()
