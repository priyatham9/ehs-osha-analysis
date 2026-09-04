"""Official NAICS 3-digit (subsector) titles.

Establishment-supplied ``industry_description`` in the OSHA ITA files describes
the establishment's own 6-digit industry, so the modal description inside a
3-digit group is NOT the name of that group. Labelling NAICS 238 "Electrical
contractors" because most of its establishments describe themselves that way
misnames a subsector that also contains plumbing, roofing, framing and masonry
contractors.

The titles below are the authoritative 3-digit subsector names. They were
extracted programmatically (not transcribed by hand) from the US Census Bureau
2022 NAICS structure file:

    https://www.census.gov/naics/2022NAICS/2-6%20digit_2022_Codes.xlsx

retrieved 2026-09-04. Trailing ``T`` markers, which that file uses to flag
titles carrying a US-specific detail note, are stripped.

The OSHA files carry 2012, 2017 or 2022 vintage NAICS codes (see the
``naics_year`` field, documented in OSHA's summary data dictionary). Subsector
boundaries are stable across those vintages for most codes but not all: the
2022 revision restructured retail trade (44-45) in particular, so a title here
describes the 2022 subsector and a filing coded under an earlier vintage may
sit in a differently-drawn group. A code with no entry returns ``None`` rather
than a guess.
"""

from __future__ import annotations

from typing import Dict, Optional

#: NAICS 2022 subsector code -> official title.
NAICS3_TITLES: Dict[str, str] = {
    "111": "Crop Production",
    "112": "Animal Production and Aquaculture",
    "113": "Forestry and Logging",
    "114": "Fishing, Hunting and Trapping",
    "115": "Support Activities for Agriculture and Forestry",
    "211": "Oil and Gas Extraction",
    "212": "Mining (except Oil and Gas)",
    "213": "Support Activities for Mining",
    "221": "Utilities",
    "236": "Construction of Buildings",
    "237": "Heavy and Civil Engineering Construction",
    "238": "Specialty Trade Contractors",
    "311": "Food Manufacturing",
    "312": "Beverage and Tobacco Product Manufacturing",
    "313": "Textile Mills",
    "314": "Textile Product Mills",
    "315": "Apparel Manufacturing",
    "316": "Leather and Allied Product Manufacturing",
    "321": "Wood Product Manufacturing",
    "322": "Paper Manufacturing",
    "323": "Printing and Related Support Activities",
    "324": "Petroleum and Coal Products Manufacturing",
    "325": "Chemical Manufacturing",
    "326": "Plastics and Rubber Products Manufacturing",
    "327": "Nonmetallic Mineral Product Manufacturing",
    "331": "Primary Metal Manufacturing",
    "332": "Fabricated Metal Product Manufacturing",
    "333": "Machinery Manufacturing",
    "334": "Computer and Electronic Product Manufacturing",
    "335": "Electrical Equipment, Appliance, and Component Manufacturing",
    "336": "Transportation Equipment Manufacturing",
    "337": "Furniture and Related Product Manufacturing",
    "339": "Miscellaneous Manufacturing",
    "423": "Merchant Wholesalers, Durable Goods",
    "424": "Merchant Wholesalers, Nondurable Goods",
    "425": "Wholesale Trade Agents and Brokers",
    "441": "Motor Vehicle and Parts Dealers",
    "444": "Building Material and Garden Equipment and Supplies Dealers",
    "445": "Food and Beverage Retailers",
    "449": "Furniture, Home Furnishings, Electronics, and Appliance Retailers",
    "455": "General Merchandise Retailers",
    "456": "Health and Personal Care Retailers",
    "457": "Gasoline Stations and Fuel Dealers",
    "458": "Clothing, Clothing Accessories, Shoe, and Jewelry Retailers",
    "459": "Sporting Goods, Hobby, Musical Instrument, Book, and Miscellaneous Retailers",
    "481": "Air Transportation",
    "482": "Rail Transportation",
    "483": "Water Transportation",
    "484": "Truck Transportation",
    "485": "Transit and Ground Passenger Transportation",
    "486": "Pipeline Transportation",
    "487": "Scenic and Sightseeing Transportation",
    "488": "Support Activities for Transportation",
    "491": "Postal Service",
    "492": "Couriers and Messengers",
    "493": "Warehousing and Storage",
    "512": "Motion Picture and Sound Recording Industries",
    "513": "Publishing Industries",
    "516": "Broadcasting and Content Providers",
    "517": "Telecommunications",
    "518": "Computing Infrastructure Providers, Data Processing, Web Hosting, and Related Services",
    "519": "Web Search Portals, Libraries, Archives, and Other Information Services",
    "521": "Monetary Authorities-Central Bank",
    "522": "Credit Intermediation and Related Activities",
    "523": "Securities, Commodity Contracts, and Other Financial Investments and Related Activities",
    "524": "Insurance Carriers and Related Activities",
    "525": "Funds, Trusts, and Other Financial Vehicles",
    "531": "Real Estate",
    "532": "Rental and Leasing Services",
    "533": "Lessors of Nonfinancial Intangible Assets (except Copyrighted Works)",
    "541": "Professional, Scientific, and Technical Services",
    "551": "Management of Companies and Enterprises",
    "561": "Administrative and Support Services",
    "562": "Waste Management and Remediation Services",
    "611": "Educational Services",
    "621": "Ambulatory Health Care Services",
    "622": "Hospitals",
    "623": "Nursing and Residential Care Facilities",
    "624": "Social Assistance",
    "711": "Performing Arts, Spectator Sports, and Related Industries",
    "712": "Museums, Historical Sites, and Similar Institutions",
    "713": "Amusement, Gambling, and Recreation Industries",
    "721": "Accommodation",
    "722": "Food Services and Drinking Places",
    "811": "Repair and Maintenance",
    "812": "Personal and Laundry Services",
    "813": "Religious, Grantmaking, Civic, Professional, and Similar Organizations",
    "814": "Private Households",
    "921": "Executive, Legislative, and Other General Government Support",
    "922": "Justice, Public Order, and Safety Activities",
    "923": "Administration of Human Resource Programs",
    "924": "Administration of Environmental Quality Programs",
    "925": "Administration of Housing Programs, Urban Planning, and Community Development",
    "926": "Administration of Economic Programs",
    "927": "Space Research and Technology",
    "928": "National Security and International Affairs",
}


def naics3_title(code: object) -> Optional[str]:
    """Return the official NAICS 2022 subsector title for a 3-digit code.

    Args:
        code: A 3-digit NAICS subsector code, as ``str`` or ``int``.

    Returns:
        The official title, or ``None`` if the code is not a known 2022
        subsector. Never returns a guessed or establishment-supplied label.
    """
    if code is None:
        return None
    key = str(code).strip()
    if key.endswith(".0"):
        key = key[:-2]
    return NAICS3_TITLES.get(key)
