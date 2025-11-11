from flask import Flask, render_template, request, redirect, url_for, send_file, flash
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from datetime import datetime, timedelta
import io
import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

# Load .env for local dev (ignored on Vercel, works locally)
load_dotenv()

# ---------------------------------------------------------------------
# ✅ Firebase Initialization (Loads from Vercel environment variable)
# ---------------------------------------------------------------------
firebase_key_json = os.environ.get("FIREBASE_KEY_JSON")  # <-- SAME NAME AS IN VERCEL ENV
if not firebase_key_json:
    raise Exception("🔥 ERROR: FIREBASE_KEY_JSON environment variable not set!")

cred_dict = json.loads(firebase_key_json)
cred = credentials.Certificate(cred_dict)

# Prevent firebase_admin.initialize_app() from running twice
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ---------------------------------------------------------------------
# ✅ Flask App Setup
# ---------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "supersecretkey")

# ---------------------------------------------------------------------
# ✅ Static credentials (login)
# ---------------------------------------------------------------------
USERNAME = "kitstechlearning.co.in"
PASSWORD = "kits@9876"

# ---------------------------------------------------------------------
# ✅ Routes
# ---------------------------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def login():
    """Simple static login."""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username == USERNAME and password == PASSWORD:
            return redirect(url_for("index"))
        else:
            flash("Invalid username or password!", "error")
            return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/index", methods=["GET"])
def index():
    """Show all invoices from Firestore."""
    invoices_ref = db.collection("invoices").stream()
    invoices = [doc.to_dict() | {"doc_id": doc.id} for doc in invoices_ref]

    search_query = request.args.get("search", "").strip().lower()
    if search_query:
        invoices = [
            inv for inv in invoices
            if search_query in inv.get("client_name", "").lower()
            or search_query in str(inv.get("invoice_no", "")).lower()
        ]

    return render_template("index.html", invoices=invoices, search_query=search_query)


# Department short codes for invoice prefixes
DEPARTMENT_CODES = {
    "robotics": "ROB",
    "it_arvr": "IT",
    "3dprinting": "3DP"
}

@app.route("/create", methods=["GET", "POST"])
def create_invoice():
    """Create a new invoice and store it in Firestore."""
    if request.method == "POST":
        client_name = request.form["client_name"]
        client_email = request.form.get("client_email", "")
        client_phone = request.form.get("client_phone", "")
        client_address = request.form.get("client_address", "")
        description = request.form.get("description", "")
        invoice_date = request.form.get("invoice_date", datetime.now().strftime("%Y-%m-%d"))
        due_date = request.form.get("due_date", (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"))

        selected_departments = request.form.getlist("departments")
        if not selected_departments:
            flash("Please select at least one department.", "danger")
            return redirect(url_for("create_invoice"))

        first_dept = selected_departments[0]
        dept_code = DEPARTMENT_CODES.get(first_dept, "GEN")
        invoices = db.collection("invoices").where("department_code", "==", dept_code).stream()
        count = sum(1 for _ in invoices)
        next_number = str(count + 1).zfill(3)
        invoice_no = f"KITS-{dept_code}-{next_number}"

        service_names = request.form.getlist("service_name[]")
        quantities = request.form.getlist("quantity[]")
        amounts = request.form.getlist("amount[]")
        items = []
        subtotal = 0

        for s, q, a in zip(service_names, quantities, amounts):
            try:
                q = int(q)
                a = float(a)
                total = q * a
                items.append({"service_name": s, "quantity": q, "amount": a, "total": total})
                subtotal += total
            except ValueError:
                continue

        cgst = request.form.get("cgst")
        sgst = request.form.get("sgst")
        gst_rate = 18 if (cgst and sgst) else 9 if (cgst or sgst) else 0
        gst_amount = round((subtotal * gst_rate) / 100, 2)
        final_total = round(subtotal + gst_amount, 2)

        invoice_data = {
            "invoice_no": invoice_no,
            "client_name": client_name,
            "client_email": client_email,
            "client_phone": client_phone,
            "client_address": client_address,
            "description": description,
            "invoice_date": invoice_date,
            "due_date": due_date,
            "items": items,
            "subtotal": subtotal,
            "gst_rate": gst_rate,
            "gst_amount": gst_amount,
            "final_total": final_total,
            "created_at": datetime.now().isoformat(),
            "departments": selected_departments,
            "department_code": dept_code
        }

        doc_ref = db.collection("invoices").add(invoice_data)
        doc_id = doc_ref[1].id

        flash(f"Invoice {invoice_no} created successfully!", "success")
        return redirect(url_for("view_invoice", doc_id=doc_id))

    return render_template("create_invoice.html")


@app.route("/invoice/<string:doc_id>")
def view_invoice(doc_id):
    doc_ref = db.collection("invoices").document(doc_id).get()
    if not doc_ref.exists:
        return "Invoice not found", 404

    invoice = doc_ref.to_dict()
    invoice["id"] = doc_id

    dept_names = invoice.get("departments", [])
    company_name = "KAJAL INNOVATION AND TECHNICAL SOLUTIONS"
    if "it_arvr" in dept_names:
        company_name = "KITS Software Solution Pvt Ltd"
    elif "robotics" in dept_names:
        company_name = "KITS Robotics and Automation Pvt Ltd"
    elif "3dprinting" in dept_names:
        company_name = "KITS 3D Printing Pvt Ltd"

    gst_type = "CGST + SGST" if invoice.get("gst_rate") == 18 else "CGST or SGST" if invoice.get("gst_rate") == 9 else "None"

    company_info = {
        "name": company_name,
        "address": "KITS, 1st floor, Mukta Plaza, KITS Square, Income tax chowk, AKOLA",
        "email": "info@kitstechlearning.co.in",
        "phone": "9226983129 / 7385582242",
        "website": "www.kitstechlearning.co.in",
        "logo": "/static/company_logo.jpg",
        "gst_type": gst_type
    }

    return render_template("view_invoice.html", invoice=invoice, company=company_info)


@app.route("/delete/<doc_id>", methods=["POST"])
def delete_invoice(doc_id):
    try:
        invoice_ref = db.collection("invoices").document(doc_id)
        if invoice_ref.get().exists:
            invoice_ref.delete()
            flash("✅ Invoice deleted successfully!", "success")
        else:
            flash("⚠️ Invoice not found in Firestore.", "warning")
    except Exception as e:
        flash(f"❌ Error deleting invoice: {e}", "error")

    return redirect(url_for("index"))


@app.route("/invoice/<string:doc_id>/download_pdf")
def download_invoice_pdf(doc_id):
    doc_ref = db.collection("invoices").document(doc_id).get()
    if not doc_ref.exists:
        return "Invoice not found", 404

    invoice = doc_ref.to_dict()

    pdf_buffer = io.BytesIO()
    c = canvas.Canvas(pdf_buffer, pagesize=A4)
    width, height = A4

    company_logo_path = "static/company_logo.jpg"

    if os.path.exists(company_logo_path):
        c.saveState()
        c.setFillAlpha(0.08)
        c.drawImage(company_logo_path, (width - 300) / 2, (height - 300) / 2, 300, 300, mask="auto")
        c.restoreState()

    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(width / 2, height - 150, invoice.get("invoice_no", ""))

    c.save()
    pdf_buffer.seek(0)

    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=f"invoice_{invoice.get('invoice_no', 'invoice')}.pdf",
        mimetype="application/pdf"
    )


# ---------------------------------------------------------------------
# ✅ Required for Vercel Serverless Deployment
# ---------------------------------------------------------------------
def handler():      # <-- NO event/context here
    return app
