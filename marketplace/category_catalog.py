"""Launch category catalogue for GhanaMarket.

Pure data, used by migration 0011 and the ``seed_categories`` command. Seeding only creates
missing rows; anything an admin has edited in Django admin is left untouched.

Attribute tuples: (key, label, kind, options) where options may include
``choices`` (list), ``unit``, ``required``, ``filterable`` and ``help``.
"""

YES_NO = "boolean"

STORAGE = ["16 GB", "32 GB", "64 GB", "128 GB", "256 GB", "512 GB", "1 TB"]
RAM = ["2 GB", "3 GB", "4 GB", "6 GB", "8 GB", "12 GB", "16 GB", "32 GB"]

CATALOG = [
    {
        "slug": "phones-tech", "name": "Phones & Tech", "icon": "phones-tech",
        "subcategories": [
            ("mobile-phones", "Mobile phones"), ("tablets", "Tablets"),
            ("phone-accessories", "Phone accessories"), ("smart-watches", "Smart watches & wearables"),
        ],
        "attributes": [
            ("storage", "Storage", "choice", {"choices": STORAGE}),
            ("ram", "RAM", "choice", {"choices": RAM}),
            ("colour", "Colour", "text", {"filterable": False}),
        ],
    },
    {
        "slug": "electronics", "name": "Computers & Electronics", "icon": "electronics",
        "subcategories": [
            ("laptops", "Laptops"), ("desktops", "Desktop computers"), ("tv-audio", "TV & audio"),
            ("cameras", "Cameras"), ("gaming", "Video games & consoles"), ("home-appliances", "Home appliances"),
        ],
        "attributes": [
            ("processor", "Processor", "text", {"filterable": False}),
            ("ram", "RAM", "choice", {"choices": RAM}),
            ("storage", "Storage", "choice", {"choices": STORAGE}),
            ("screen_size", "Screen size", "number", {"unit": "in", "filterable": False}),
        ],
    },
    {
        "slug": "fashion", "name": "Fashion", "icon": "fashion",
        "subcategories": [
            ("mens-clothing", "Men's clothing"), ("womens-clothing", "Women's clothing"), ("shoes", "Shoes"),
            ("bags", "Bags"), ("watches-jewellery", "Watches & jewellery"), ("traditional-wear", "Kente & traditional wear"),
        ],
        "attributes": [
            ("gender", "For", "choice", {"choices": ["Men", "Women", "Unisex", "Boys", "Girls"]}),
            ("size", "Size", "text", {}),
            ("colour", "Colour", "text", {"filterable": False}),
        ],
    },
    {
        "slug": "vehicles", "name": "Cars & Vehicles", "icon": "vehicles", "allows_checkout": False,
        "subcategories": [
            ("cars", "Cars"), ("motorcycles", "Motorcycles & scooters"),
            ("trucks-buses", "Trucks, buses & vans"), ("vehicle-parts", "Vehicle parts & accessories"),
        ],
        "attributes": [
            ("make", "Make", "choice", {"choices": [
                "Toyota", "Honda", "Hyundai", "Kia", "Nissan", "Mercedes-Benz", "BMW", "Ford",
                "Volkswagen", "Mitsubishi", "Suzuki", "Lexus", "Other",
            ]}),
            ("year", "Year of manufacture", "number", {}),
            ("mileage", "Mileage", "number", {"unit": "km"}),
            ("transmission", "Transmission", "choice", {"choices": ["Automatic", "Manual"]}),
            ("fuel", "Fuel", "choice", {"choices": ["Petrol", "Diesel", "Hybrid", "Electric", "LPG"]}),
        ],
    },
    {
        "slug": "property", "name": "Property", "icon": "property", "allows_checkout": False, "price_label": "Price",
        "subcategories": [
            ("houses-for-rent", "Houses & apartments for rent"), ("houses-for-sale", "Houses & apartments for sale"),
            ("land", "Land & plots"), ("commercial-property", "Shops & offices"), ("short-stay", "Short stay"),
        ],
        "attributes": [
            ("listing_type", "Listing type", "choice", {"choices": ["For rent", "For sale", "Short stay"], "required": True}),
            ("bedrooms", "Bedrooms", "number", {}),
            ("bathrooms", "Bathrooms", "number", {}),
            ("furnished", "Furnished", YES_NO, {}),
            ("size_sqm", "Size", "number", {"unit": "m²", "filterable": False}),
        ],
    },
    {
        "slug": "home-living", "name": "Home & Living", "icon": "home-living",
        "subcategories": [
            ("furniture", "Furniture"), ("kitchen", "Kitchen & dining"), ("home-decor", "Home décor"),
            ("garden", "Garden & outdoor"), ("household", "Household supplies"),
        ],
        "attributes": [("material", "Material", "text", {"filterable": False})],
    },
    {
        "slug": "health-beauty", "name": "Health & Beauty", "icon": "health-beauty",
        "subcategories": [
            ("skincare", "Skin care"), ("hair", "Hair & wigs"), ("fragrances", "Fragrances"),
            ("personal-care", "Personal care"),
        ],
        "attributes": [],
    },
    {
        "slug": "baby-kids", "name": "Babies & Kids", "icon": "baby-kids",
        "subcategories": [("baby-gear", "Baby gear"), ("kids-clothing", "Children's clothing"), ("toys", "Toys & games")],
        "attributes": [("age_range", "Age range", "text", {})],
    },
    {
        "slug": "food-agriculture", "name": "Food & Agriculture", "icon": "food-agriculture",
        "subcategories": [
            ("groceries", "Groceries"), ("farm-produce", "Farm produce"), ("livestock", "Livestock & poultry"),
            ("farm-equipment", "Farm machinery & inputs"),
        ],
        "attributes": [("quantity", "Quantity / unit", "text", {"help": "e.g. 50 kg bag, crate of 30", "filterable": False})],
    },
    {
        "slug": "sports-outdoors", "name": "Sports & Outdoors", "icon": "sports-outdoors",
        "subcategories": [("fitness", "Fitness equipment"), ("bicycles", "Bicycles"), ("outdoor", "Camping & outdoor")],
        "attributes": [],
    },
    {
        "slug": "jobs", "name": "Jobs", "icon": "jobs", "allows_checkout": False, "price_label": "Monthly salary",
        "subcategories": [("full-time", "Full-time"), ("part-time", "Part-time & casual"), ("internships", "Internships")],
        "attributes": [
            ("job_type", "Job type", "choice", {"choices": ["Full-time", "Part-time", "Contract", "Internship"], "required": True}),
            ("experience", "Experience level", "choice", {"choices": ["Entry level", "Mid level", "Senior"]}),
        ],
    },
    {
        "slug": "business-services", "name": "Services", "icon": "business-services", "allows_checkout": False,
        "price_label": "Starting price",
        "subcategories": [
            ("repair", "Repairs & maintenance"), ("cleaning", "Cleaning"), ("event-services", "Event services"),
            ("beauty-services", "Beauty services"), ("transport-logistics", "Transport & logistics"),
            ("professional-services", "Professional services"),
        ],
        "attributes": [],
    },
    {
        "slug": "education-books", "name": "Books & Education", "icon": "education-books",
        "subcategories": [("books", "Books"), ("courses", "Classes & courses"), ("stationery", "Stationery")],
        "attributes": [],
    },
    {
        "slug": "industrial-tools", "name": "Tools & Machinery", "icon": "industrial-tools",
        "subcategories": [("power-tools", "Power tools"), ("generators", "Generators & power"), ("machinery", "Industrial machinery")],
        "attributes": [],
    },
    {
        "slug": "construction", "name": "Building & Construction", "icon": "construction",
        "subcategories": [("building-materials", "Building materials"), ("plumbing-electrical", "Plumbing & electrical")],
        "attributes": [],
    },
    {
        "slug": "music-events", "name": "Music & Entertainment", "icon": "music-events",
        "subcategories": [("instruments", "Musical instruments"), ("audio-equipment", "DJ & audio equipment")],
        "attributes": [],
    },
    {
        "slug": "other", "name": "Other", "icon": "other",
        "subcategories": [],
        "attributes": [],
    },
]


def seed_catalog(Category, CategoryAttribute):
    """Create any missing catalogue rows. Works with real or historical (migration) models."""
    created = 0
    for position, entry in enumerate(CATALOG):
        top, was_created = Category.objects.get_or_create(
            slug=entry["slug"],
            defaults={
                "name": entry["name"],
                "icon": entry.get("icon", ""),
                "position": position,
                "allows_checkout": entry.get("allows_checkout", True),
                "price_label": entry.get("price_label", ""),
            },
        )
        created += was_created
        for sub_position, (slug, name) in enumerate(entry["subcategories"]):
            _, was_created = Category.objects.get_or_create(
                slug=slug,
                defaults={"name": name, "parent": top, "position": sub_position,
                          "allows_checkout": entry.get("allows_checkout", True)},
            )
            created += was_created
        for attr_position, (key, label, kind, options) in enumerate(entry["attributes"]):
            _, was_created = CategoryAttribute.objects.get_or_create(
                category=top, key=key,
                defaults={
                    "label": label, "kind": kind, "choices": "\n".join(options.get("choices", [])),
                    "unit": options.get("unit", ""), "help_text": options.get("help", ""),
                    "is_required": options.get("required", False),
                    "is_filterable": options.get("filterable", True), "position": attr_position,
                },
            )
            created += was_created
    return created
