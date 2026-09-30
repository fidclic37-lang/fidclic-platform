"""
CRM › Import — every usual file, read exactly: PDF tables (cells over several
lines, a table going on to the next page, several tables, a table that is not
a list of businesses), Excel, LibreOffice, Word, CSV with titles above the
table, JSON, HTML, vCard, RTF; duplicates in the file merged; the preview's
default city.

Run: cd api && /usr/local/bin/python3 tests/test_crm_import_formats.py
"""
import io
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from features import crm_import as I  # noqa: E402

passed = failed = 0


def check(label, cond):
    global passed, failed
    passed += bool(cond); failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def names(rows):
    return [r["name"] for r in rows]


# ---------------------------------------------------------------- PDF
def make_pdf() -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    st = getSampleStyleSheet()["BodyText"]
    P = lambda t: Paragraph(t, st)       # noqa: E731 — wraps inside its cell
    grid = TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")])
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    story = [Paragraph("RESTAURANTS", getSampleStyleSheet()["Title"]),
             # not a list of businesses: must be ignored
             Table([["Sous-segment", "Clientèle", "Fréquence d'achat"], ["Fast-food", "Jeunes, étudiants", "Très élevée"]], style=grid),
             Spacer(1, 20)]
    head = ["#", "Commerce", "Segment", "Adresse", "Téléphone"]
    data = [head]
    for i in range(1, 31):
        data.append([str(i), P(f"Restaurant Numéro {i} - Tours"), P("Restauration rapide"), P(f"{i} Rue du Grand Marché"),
                     P(f"02 47 64 {i:02d} 71")])
    story.append(Table(data, colWidths=[25, 150, 100, 110, 70], style=grid, repeatRows=0))   # goes on to page 2, no header
    story += [PageBreak(), Table([["#", "Établissement", "Sous-segment", "Adresse", "Téléphone"],
                                  ["1", P("Restaurant Numéro 3 - Tours"), "Pizzeria", P("3 Rue du Grand Marché"), "—"],
                                  ["2", "Le Pavillon", "Traditionnel", "Tours", "—"],
                                  ["3", P("Le Chien Jaune"), "Bistrot", P("74 Rue Bernard-Palissy"), "—"]], style=grid)]
    doc.build(story)
    return buf.getvalue()


print("\nPDF tables")
pdf = make_pdf()
rows, merged = I.parse_with_stats("liste.pdf", pdf)
by = {r["name"]: r for r in rows}
check("every row of a 2-page table, plus the second table", len(rows) == 32)
check("the characteristics table is not taken for businesses", "Fast-food" not in by and "Sous-segment" not in by)
check("a name over two lines stays one name", "Restaurant Numéro 12 - Tours" in by)
check("a phone over two lines stays whole", by["Restaurant Numéro 12 - Tours"]["phone"] == "02 47 64 12 71")
check("the rows on page 2 (no header there) keep their columns",
      by["Restaurant Numéro 30 - Tours"]["address"] == "30 Rue du Grand Marché" and by["Restaurant Numéro 30 - Tours"]["sector"] == "Restauration rapide")
check("the same business in two tables: once", merged == 1 and names(rows).count("Restaurant Numéro 3 - Tours") == 1)
check("« — » is an empty cell", by["Le Chien Jaune"]["phone"] == "")
check("« Tours » alone as address is the city", by["Le Pavillon"]["city"] == "Tours" and by["Le Pavillon"]["address"] == "")
check("a hyphenated word over two lines is joined", by["Le Chien Jaune"]["address"].replace(" ", "") in ("74RueBernard-Palissy",))

# ---------------------------------------------------------------- Excel
print("\nExcel, LibreOffice, Word")
from openpyxl import Workbook  # noqa: E402
wb = Workbook()
ws = wb.active
ws.append(["Prospects Tours — septembre"])            # a title above the table
ws.append([])
ws.append(["Nom du commerce", "Ville", "Téléphone", "Email"])
ws.append(["Café des Arts", "Orléans", 238000004, "arts@ex.fr"])   # the leading 0 lost in a number cell
ws.append(["Snak", "Tours", "—", None])
ws2 = wb.create_sheet("Autres")
ws2.append(["Enseigne", "Adresse", "Code postal"])
ws2.append(["Chez Pia", "9 Rue de Châteauneuf", 37000])
b = io.BytesIO(); wb.save(b)
x = I.parse("prospects.xlsx", b.getvalue())
xb = {r["name"]: r for r in x}
check("XLSX: header below a title, every sheet", set(xb) == {"Café des Arts", "Snak", "Chez Pia"})
check("XLSX: phone number cell gets its 0 back", xb["Café des Arts"]["phone"] == "02 38 00 00 04")
check("XLSX: numbers without .0", xb["Chez Pia"]["postal_code"] == "37000")


def odf(kind: str, body: str) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("mimetype", f"application/vnd.oasis.opendocument.{kind}")
        z.writestr("content.xml", '<?xml version="1.0"?><office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
                   'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
                   f'<office:body>{body}</office:body></office:document-content>')
    return b.getvalue()


cell = lambda t: f'<table:table-cell><text:p>{t}</text:p></table:table-cell>'   # noqa: E731
row = lambda *c: "<table:table-row>" + "".join(cell(t) for t in c) + "</table:table-row>"   # noqa: E731
ods = odf("spreadsheet", "<table:table>" + row("Commerce", "Téléphone") + row("Le Mastroquet", "02 47 61 48 21") + "</table:table>")
check("ODS", names(I.parse("liste.ods", ods)) == ["Le Mastroquet"])

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
wc = lambda t: f"<w:tc><w:p><w:r><w:t>{t}</w:t></w:r></w:p></w:tc>"   # noqa: E731
docx = io.BytesIO()
with zipfile.ZipFile(docx, "w") as z:
    z.writestr("word/document.xml", f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>Liste</w:t></w:r></w:p><w:tbl>'
               f"<w:tr>{wc('Restaurant')}{wc('Adresse')}{wc('Téléphone')}</w:tr>"
               f"<w:tr>{wc('Verjus')}{wc('50 Rue du Grand Marché')}{wc('02 47 36 94 82')}</w:tr></w:tbl></w:body></w:document>")
d = I.parse("liste.docx", docx.getvalue())
check("DOCX table", names(d) == ["Verjus"] and d[0]["phone"] == "02 47 36 94 82")

# ---------------------------------------------------------------- text formats
print("\nCSV, JSON, HTML, vCard, RTF, anything else")
csv_text = "Liste des prospects\nExport du 30/09\n\nNom;Ville;Téléphone\nBella Vista;Tours;02 47 00 00 01\nBella Vista;Tours;02 47 00 00 01\n"
rows, merged = I.parse_with_stats("liste.csv", csv_text.encode("cp1252"))
check("CSV with titles above, in Windows encoding, duplicate merged", names(rows) == ["Bella Vista"] and merged == 1)
check("TSV", names(I.parse("x.tsv", b"Commerce\tVille\nNobuki\tTours\n")) == ["Nobuki"])
j = json.dumps({"prospects": [{"nom": "Jaspe", "telephone": "0247054832", "adresse": {"ville": "Tours"}}]}).encode()
jr = I.parse("export.json", j)
check("JSON", names(jr) == ["Jaspe"] and jr[0]["phone"] == "02 47 05 48 32")
html = b"<html><body><h1>Liste</h1><table><tr><th>Enseigne</th><th>Email</th></tr><tr><td>La Dinette</td><td>contact@dinette.fr</td></tr></table></body></html>"
check("HTML table", names(I.parse("page.html", html)) == ["La Dinette"])
vcf = b"BEGIN:VCARD\nVERSION:3.0\nFN:Marie Dupont\nORG:Le Petit Zinc\nTEL:02 47 00 00 02\nEMAIL:zinc@ex.fr\nEND:VCARD\n"
v = I.parse("contacts.vcf", vcf)
check("vCard", names(v) == ["Le Petit Zinc"] and v[0]["contact_name"] == "Marie Dupont")
rtf = rb"{\rtf1\ansi Nom : Caf\'e9 Joyeux\par T\'e9l\'e9phone : 01 87 53 64 80\par}"
r = I.parse("notes.rtf", rtf)
check("RTF", r and r[0]["phone"] == "01 87 53 64 80")
check("any other text file", names(I.parse("liste.dat", b"Nom;Ville\nCase.;Tours\n")) == ["Case."])
try:
    I.parse("photo.jpg", b"\xff\xd8\xff")
    check("an image is refused with the list of formats", False)
except ValueError as e:
    check("an image is refused with the list of formats", "xlsx" in str(e))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
