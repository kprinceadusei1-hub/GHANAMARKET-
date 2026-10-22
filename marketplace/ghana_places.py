"""Main towns and neighbourhoods by Ghana region, used for city suggestions on forms.

Suggestions only: people may type any town not listed here.
"""
TOWNS_BY_REGION = {
    "Greater Accra": ["Accra", "Tema", "Madina", "Adenta", "Ashaiman", "Teshie", "Nungua", "Dansoman", "Spintex",
                      "East Legon", "Osu", "Kaneshie", "Achimota", "Dome", "Haatso", "Lapaz", "Weija", "Dodowa",
                      "Kpone", "Prampram", "Ada"],
    "Ashanti": ["Kumasi", "Obuasi", "Ejisu", "Konongo", "Mampong", "Bekwai", "Offinso", "Ejura", "Agogo", "Tafo",
                "Suame"],
    "Central": ["Cape Coast", "Kasoa", "Winneba", "Mankessim", "Elmina", "Saltpond", "Agona Swedru",
                "Dunkwa-on-Offin", "Assin Fosu"],
    "Eastern": ["Koforidua", "Nkawkaw", "Nsawam", "Akim Oda", "Suhum", "Somanya", "Aburi", "Kibi", "Akosombo",
                "Asamankese"],
    "Western": ["Takoradi", "Sekondi", "Tarkwa", "Prestea", "Axim", "Shama"],
    "Western North": ["Sefwi Wiawso", "Bibiani", "Juaboso", "Enchi"],
    "Volta": ["Ho", "Hohoe", "Keta", "Aflao", "Kpando", "Sogakope", "Anloga"],
    "Oti": ["Dambai", "Jasikan", "Nkwanta", "Kadjebi"],
    "Bono": ["Sunyani", "Berekum", "Dormaa Ahenkro", "Wenchi"],
    "Bono East": ["Techiman", "Kintampo", "Atebubu", "Nkoranza"],
    "Ahafo": ["Goaso", "Bechem", "Duayaw Nkwanta", "Kenyasi"],
    "Northern": ["Tamale", "Yendi", "Savelugu", "Bimbilla"],
    "Savannah": ["Damongo", "Salaga", "Bole", "Sawla"],
    "North East": ["Nalerigu", "Walewale", "Gambaga"],
    "Upper East": ["Bolgatanga", "Bawku", "Navrongo", "Paga", "Zebilla"],
    "Upper West": ["Wa", "Tumu", "Lawra", "Jirapa", "Nandom"],
}

REGION_NAMES = {region.lower() for region in TOWNS_BY_REGION} | {"ghana"}


def town_options():
    """(town, region) pairs for a <datalist>, sorted by town."""
    return sorted((town, region) for region, towns in TOWNS_BY_REGION.items() for town in towns)


def clean_city(value):
    """Tidy a typed town name; reject region names typed into the town box."""
    from django.core.exceptions import ValidationError

    city = " ".join((value or "").split())
    if not city:
        return city
    if city.lower() in REGION_NAMES or city.lower().replace(" region", "") in REGION_NAMES:
        raise ValidationError("Enter your town or area (for example Madina or Tema), not the region.")
    known = {town.lower(): town for towns in TOWNS_BY_REGION.values() for town in towns}
    return known.get(city.lower(), city.title() if city.islower() or city.isupper() else city)
