"""
Catalogue produits — products, categories, photos, and what sells.

Run:
    cd api && python3 tests/test_catalogue_page.py
"""
import base64
import datetime as dt
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server                      # noqa: F401 — boots the app + db
    from fastapi import HTTPException
    from features import catalogue_page as K
    from features import push_wallet as PW

    db = server.db
    K.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    class TD:
        email, role, tenant_id = "owner@x.fr", "business_owner", "t1"

    def refused(fn):
        try:
            fn()
        except HTTPException as e:
            return e.detail
        return None

    now = dt.datetime.now(dt.timezone.utc)
    ago = lambda d: now - dt.timedelta(days=d)
    db.tenants.insert_one({"id": "t1", "name": "Le Corner Café", "slug": "corner"})

    print("\nAn empty catalogue")
    p = K.page(token_data=TD())
    check("reads as empty, not as an error",
          p["products"] == [] and p["kpis"] == {"total": 0, "top": 0, "inactive": 0, "avg_price": 0.0})

    print("\nAjouter un produit")
    def add(name, price, category, subtitle="", active=True):
        return K.create_product(K.ProductIn(name=name, price=price, category=category,
                                            subtitle=subtitle, active=active), token_data=TD())["id"]
    latte = add("Café Latte", 3.5, "Boissons chaudes", "Boisson chaude")
    croissant = add("Croissant", 1.8, "Pâtisseries", "Viennoiserie")
    iced = add("Iced Coffee", 3.9, "Boissons froides", "Boisson froide")
    sandwich = add("Sandwich Poulet", 5.9, "Snacks", "Restauration", active=False)
    cheesecake = add("Cheesecake", 4.5, "Pâtisseries", "Pâtisserie")
    p = K.page(token_data=TD())
    prods = {x["name"]: x for x in p["products"]}
    check("each product keeps its name, price, category and short description",
          prods["Café Latte"]["price"] == 3.5 and prods["Café Latte"]["category"] == "Boissons chaudes"
          and prods["Café Latte"]["subtitle"] == "Boisson chaude")
    check("a new category is declared with a colour of its own",
          [c["name"] for c in p["categories"]] == ["Boissons chaudes", "Pâtisseries", "Boissons froides", "Snacks"]
          and len({c["color"] for c in p["categories"]}) == 4)
    check("a product carries its category's colour",
          prods["Croissant"]["color"] == next(c["color"] for c in p["categories"] if c["name"] == "Pâtisseries"))
    check("Produits au total", p["kpis"]["total"] == 5)
    check("Produits inactifs", p["kpis"]["inactive"] == 1)
    check("Prix moyen is over the products on sale (3.5+1.8+3.9+4.5)/4 = 3.42",
          p["kpis"]["avg_price"] == 3.42)
    check("a nameless product is refused", refused(lambda: add(" ", 2, "X")))
    check("a negative price is refused", refused(lambda: add("Thé", -1, "X")))

    print("\nWhat sells (from the till)")
    db.visits.insert_many([
        {"id": "v1", "tenant_id": "t1", "visit_time": ago(2),
         "items": [{"item_id": latte, "name": "Café Latte", "price": 3.5, "qty": 3, "line_total": 10.5},
                   {"item_id": croissant, "name": "Croissant", "price": 1.8, "qty": 1, "line_total": 1.8}]},
        {"id": "v2", "tenant_id": "t1", "visit_time": ago(5),
         "items": [{"item_id": latte, "name": "Café Latte", "price": 3.5, "qty": 2, "line_total": 7.0}]},
        # an old line with no id, matched by name
        {"id": "v3", "tenant_id": "t1", "visit_time": ago(6),
         "items": [{"name": "iced coffee", "price": 3.9, "quantity": 1}]},
        # outside 30 days
        {"id": "v4", "tenant_id": "t1", "visit_time": ago(50),
         "items": [{"item_id": croissant, "name": "Croissant", "price": 1.8, "qty": 9, "line_total": 16.2}]},
        {"id": "x", "tenant_id": "t2", "visit_time": ago(1),
         "items": [{"item_id": latte, "name": "Café Latte", "qty": 50}]},
    ])
    p = K.page(token_data=TD())
    prods = {x["name"]: x for x in p["products"]}
    check("sales count the quantities recorded at the till", prods["Café Latte"]["sales"] == 5)
    check("with their revenue", prods["Café Latte"]["revenue"] == 17.5)
    check("a line written before ids existed is matched by name", prods["Iced Coffee"]["sales"] == 1)
    check("only the chosen period counts (30 days)", prods["Croissant"]["sales"] == 1)
    check("and 90 days reaches further", {x["name"]: x for x in K.page(days=90, token_data=TD())["products"]}["Croissant"]["sales"] == 10)
    check("another shop's sales never count", sum(x["sales"] for x in p["products"]) == 7)
    check("'Produits les plus vendus' = how few products make 80 % of sales (5 of 7 → Latte alone is 71 %, + Croissant)",
          p["kpis"]["top"] == 2)
    check("top_count on its own", K.top_count([10, 5, 3, 1, 1]) == 3 and K.top_count([0, 0]) == 0)
    check("the daily series spans the period", len(p["stats"]["daily"]) == 31
          and sum(d["sales"] for d in p["stats"]["daily"]) == 7)
    check("the statistics add up", p["stats"]["sales"] == 7 and p["stats"]["revenue"] == 23.2
          and p["stats"]["sold_products"] == 3)
    cats = {c["name"]: c for c in p["categories"]}
    check("each category has its product count and its sales",
          cats["Pâtisseries"]["count"] == 2 and cats["Boissons chaudes"]["sales"] == 5)

    print("\nModifier, dupliquer, activer")
    K.update_product(latte, K.ProductIn(name="Café Latte", price=3.8, category="Boissons chaudes",
                                        subtitle="Boisson chaude", active=True), token_data=TD())
    check("an edit is saved", {x["name"]: x for x in K.page(token_data=TD())["products"]}["Café Latte"]["price"] == 3.8)
    dup = K.duplicate_product(croissant, token_data=TD())
    names = [x["name"] for x in dup["products"]]
    check("a duplicate sits right after its original", names[names.index("Croissant") + 1] == "Croissant (copie)")
    out = K.bulk(K.BulkIn(ids=[sandwich, iced], action="activate"), token_data=TD())
    check("bulk activate", out["kpis"]["inactive"] == 0)
    out = K.bulk(K.BulkIn(ids=[iced], action="deactivate"), token_data=TD())
    check("bulk deactivate", out["kpis"]["inactive"] == 1)
    out = K.bulk(K.BulkIn(ids=[sandwich, cheesecake], action="category", category="Desserts"), token_data=TD())
    check("bulk move to a new category declares it",
          "Desserts" in [c["name"] for c in out["categories"]]
          and {x["name"]: x for x in out["products"]}["Sandwich Poulet"]["category"] == "Desserts")
    check("an unknown bulk action is refused", refused(lambda: K.bulk(K.BulkIn(ids=[iced], action="explode"), token_data=TD())))

    print("\nPhotos")
    png = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 100).decode()
    out = K.put_image(latte, K.ImageIn(data_url=png), token_data=TD())
    url = {x["name"]: x for x in out["products"]}["Café Latte"]["image_url"]
    check("a photo gets a URL", url and url.startswith("/api/catalogue-image/"))
    img_id = url.rsplit("/", 1)[1]
    r = K.get_image(img_id)
    check("which serves the image, cached for ever",
          r.media_type == "image/png" and "immutable" in r.headers["cache-control"])
    out = K.put_image(latte, K.ImageIn(data_url=png), token_data=TD())
    check("a new photo replaces the old one (and the old one is gone)",
          db.catalogue_images.count_documents({"id": img_id}) == 0
          and db.catalogue_images.count_documents({"tenant_id": "t1"}) == 1)
    check("not an image is refused", refused(lambda: K.put_image(latte, K.ImageIn(data_url="data:text/html;base64,PGI+"), token_data=TD())))
    big = "data:image/jpeg;base64," + base64.b64encode(b"0" * (K.MAX_IMAGE_BYTES + 1)).decode()
    check("too heavy is refused", refused(lambda: K.put_image(latte, K.ImageIn(data_url=big), token_data=TD())))
    dup2 = K.duplicate_product(latte, token_data=TD())
    copy = next(x for x in dup2["products"] if x["name"] == "Café Latte (copie)")
    check("a duplicate gets its own copy of the photo",
          copy["image_url"] and copy["image_url"] != {x["name"]: x for x in dup2["products"]}["Café Latte"]["image_url"])
    K.delete_product(copy["id"], token_data=TD())
    check("deleting a product deletes its photo", db.catalogue_images.count_documents({"tenant_id": "t1"}) == 1)

    print("\nCatégories")
    out = K.update_category(K.CategoryIn(old_name="Pâtisseries", name="Viennoiseries", color="teal"), token_data=TD())
    prods = {x["name"]: x for x in out["products"]}
    check("renaming a category moves its products", prods["Croissant"]["category"] == "Viennoiseries")
    check("and recolours it", next(c for c in out["categories"] if c["name"] == "Viennoiseries")["color"] == "teal")
    check("a duplicate name is refused",
          refused(lambda: K.create_category(K.CategoryIn(name="snacks"), token_data=TD())))
    out = K.create_category(K.CategoryIn(name="Boissons chaudes XL"), token_data=TD())
    check("an empty category can exist", next(c for c in out["categories"] if c["name"] == "Boissons chaudes XL")["count"] == 0)
    out = K.delete_category("Viennoiseries", move_to="Desserts", token_data=TD())
    check("deleting a category moves its products where the owner says",
          {x["name"]: x for x in out["products"]}["Croissant"]["category"] == "Desserts"
          and "Viennoiseries" not in [c["name"] for c in out["categories"]])
    out = K.delete_category("Snacks", move_to="", token_data=TD())
    check("an emptied category can be removed", "Snacks" not in [c["name"] for c in out["categories"]])

    print("\nImporter depuis le menu")
    out = K.import_products(K.ImportIn(items=[K.ProductIn(name="Thé vert", price=3, category="Boissons chaudes"),
                                             K.ProductIn(name="café latte", price=9, category="X")]), token_data=TD())
    check("new lines are added, a name already there is skipped",
          out["added"] == 1 and sum(1 for x in out["products"] if x["name"].lower() == "café latte") == 1)

    print("\nThe older editor and the till")
    before = {i["id"]: i for i in db.tenant_catalog.find_one({"tenant_id": "t1"})["items"]}
    server.put_owner_catalog(server.CatalogReq(items=[
        server.CatalogItemReq(id=i["id"], name=i["name"], price=i["price"], category=i.get("category"))
        for i in before.values()]), token_data=TD())
    after = {i["id"]: i for i in db.tenant_catalog.find_one({"tenant_id": "t1"})["items"]}
    check("saving from the older editor keeps photos, descriptions and on/off",
          after[latte].get("image_id") == before[latte].get("image_id")
          and after[latte].get("subtitle") == "Boisson chaude" and after[iced].get("active") is False)
    served = server.get_owner_catalog(token_data=TD())["items"]
    check("the Scan page gets the on/off flag to hide what is switched off",
          any(i.get("active") is False for i in served))

    print("\nAutomatisations · Nouveautés")
    row = {"id": "s1", "trigger": "new_product", "config": {}, "last_run_at": now - dt.timedelta(hours=1)}
    check("nothing added since the last run → nobody", PW._audience("t1", row, now) == [])
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "name": "Ana"})
    add("Muffin Chocolat", 2.9, "Desserts")
    check("a product added since → the scenario fires", len(PW._audience("t1", row, dt.datetime.now(dt.timezone.utc))) == 1)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
