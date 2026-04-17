"""Saffron & Smoke — Full restaurant menu.

Every dish has: name, category, description, how it's made, taste profile,
popularity rating (1-5 stars from customer reviews), price, quantity/serving
info, dietary tags, image URL, and availability.
"""

# Image URLs. Edit this map (not the dish entries below) if you want to swap
# images. The seeder syncs the DB to this map on every server restart.
IMAGE_URLS = {
    "S01": "https://www.jcookingodyssey.com/wp-content/uploads/2025/07/tandoori-paneer-tikka.jpg",
    "S02": "https://cdn.meatigo.com/fit-in/651x552/product/1774507134478_128_26082022_Mutton_Galouti_Kebab",
    "S03": "https://dinnerthendessert.com/wp-content/uploads/2019/02/Dynamite-Shrimp-1048x699.jpg",
    "S04": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRTUsFrRlZSNhLbz2NaeluUH28xmyqX3glb7A&s",
    "M01": "https://sugarspunrun.com/wp-content/uploads/2025/04/Butter-chicken-1-of-1.jpg",
    "M02": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQ9i0_mIQiugdza8foHQ4nbXk3aZtstphJ4XmUfqah0hdnKPix6MObQ0tYOaAursG8MXkbReM53qxd1UsP1GuPX4YbD6HAp3ehIroraMpk&s=10",
    "M03": "https://www.cookwithmanali.com/wp-content/uploads/2019/04/Restaurant-Style-Dal-Makhani-500x500.jpg",
    "M04": "https://www.cookwithkushi.com/wp-content/uploads/2023/10/best_simple_easy_chicken_dum_biryani.jpg",
    "M05": "https://www.mygingergarlickitchen.com/wp-content/rich-markup-images/1x1/1x1-paneer-lababdar.jpg",
    "M06": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQxJ9wBsb3SIbPoIx0cz3fimI4nVytblzwFAw&s",
    "B01": "https://www.pachakam.com/wp-content/uploads/2009/05/new-butter-naan-500x375.jpg",
    "B02": "https://www.supergoldenbakes.com/wordpress/wp-content/uploads/2025/09/Garlic_Naan-8.jpg",
    "B03": "https://myfoodstory.com/wp-content/uploads/2022/08/Homemade-Lachha-Paratha-3-500x500.jpg",
    "B04": "https://www.cookwithmanali.com/wp-content/uploads/2021/07/Tandoori-Roti.jpg",
    "B05": "https://encrypted-tbn3.gstatic.com/images?q=tbn:ANd9GcRmwMXH-WhrwYDhi3iBqyr2jgEIYu2H3p3szDQAe69OdRZw2c4L",
    "R01": "https://encrypted-tbn1.gstatic.com/images?q=tbn:ANd9GcT60yi3ccVhfBsXC-AwdZt1olc23xQQ_O-mVE39KcXBgFprBMvX",
    "R02": "https://lentillovingfamily.com/wp-content/uploads/2025/08/jeera-rice-1.jpg",
    "R03": "https://www.cubesnjuliennes.com/wp-content/uploads/2018/08/easy-zafrani-pulao.jpg",
    "D01": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRZkxBv6fF_co9NWR5QdDbYdn9GeI6BsoIVwQ&s",
    "D02": "https://heygrillhey.com/wp-content/uploads/2016/08/DarkChocolateCaramelBrownies-9-1024x683.jpg",
    "D03": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcR1qaiQwm3oD69PVQ4xyTrIYdP7pmb0hvd9fg&s",
    "BV01": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTZSN-4gCIBidVIdKWMbdQ9WwPZ1_L6Jdu6uC4dGpWfvkvUQORu_dfc73bbTSupmyYCigu8moUV_qfnJ5KE4RW5xDL_2SvbeNQtXfp5EA&s=10",
    "BV02": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcSqI-OkqueI6TYqRETquHMeKM-iLxEin3d2JQ&s",
    "BV03": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTFpRGVWgownVY1dSYMy7XezSeSSaqHaTz58Q&s",
    "BV04": "https://www.dhampurgreen.com/cdn/shop/files/76080679-1cdc-451d-96e8-864a495df78e.webp?v=1774436750",
    "BV05": "https://mytastycurry.com/wp-content/uploads/2020/04/Cafe-style-cold-coffee-with-icecream.jpg",
    "BV06": "https://m.media-amazon.com/images/I/61u0Ot8PIOL._AC_UF894,1000_QL80_.jpg",
}


MENU = {
    "starters": [
        {
            "id": "S01",
            "name": "Tandoori Paneer Tikka",
            "price": 320,
            "currency": "INR",
            "serving": "6 pieces",
            "description": "Cottage cheese cubes marinated in hung curd, Kashmiri chili, and charcoal-grilled in our clay tandoor.",
            "how_its_made": "Paneer is marinated for 4 hours in a blend of hung curd, ginger-garlic paste, Kashmiri red chili, garam masala, and mustard oil. Skewered and cooked in a live tandoor at 300°C until edges char slightly.",
            "taste_profile": "Smoky, mildly spicy, creamy inside with a charred crust. The mustard oil gives a subtle pungent kick.",
            "popularity": 4.6,
            "popularity_note": "Our most ordered starter. Regulars ask for extra char.",
            "dietary": ["vegetarian", "gluten-free"],
            "spice_level": "medium",
            "available": True,
        },
        {
            "id": "S02",
            "name": "Lamb Galouti Kebab",
            "price": 450,
            "currency": "INR",
            "serving": "4 pieces with ulte tawa ka paratha",
            "description": "Melt-in-your-mouth minced lamb kebabs from a 200-year-old Lucknowi recipe, served on griddle-pressed paratha.",
            "how_its_made": "Finely minced lamb is mixed with over 30 spices including raw papaya (tenderizer), mace, cardamom, and rose petal powder. Shallow-fried on a flat griddle until a thin crust forms while staying molten inside.",
            "taste_profile": "Incredibly tender, almost paste-like texture. Rich, aromatic, with floral undertones from rose and a warm spice finish.",
            "popularity": 4.8,
            "popularity_note": "Chef's pride. Customers say it's the best galouti outside Lucknow.",
            "dietary": ["non-vegetarian", "contains-gluten"],
            "spice_level": "mild",
            "available": True,
        },
        {
            "id": "S03",
            "name": "Dynamite Prawns",
            "price": 520,
            "currency": "INR",
            "serving": "8 pieces",
            "description": "Crispy battered tiger prawns tossed in our house sriracha-mayo with curry leaf tempura.",
            "how_its_made": "Tiger prawns are coated in a rice flour and cornstarch batter, deep-fried until golden. Tossed in a sauce of sriracha, Japanese mayo, honey, and lime. Topped with flash-fried curry leaves.",
            "taste_profile": "Crunchy exterior, juicy prawns, creamy-spicy sauce with a citrus lift. The curry leaves add an aromatic crunch.",
            "popularity": 4.4,
            "popularity_note": "Popular with younger crowd. Great with cocktails.",
            "dietary": ["non-vegetarian", "contains-gluten", "contains-shellfish"],
            "spice_level": "medium-hot",
            "available": True,
        },
        {
            "id": "S04",
            "name": "Smoked Beetroot Hummus",
            "price": 280,
            "currency": "INR",
            "serving": "bowl with lavash crisps",
            "description": "Wood-smoked beetroot blended with tahini, roasted garlic, and sumac. Served with house-baked lavash.",
            "how_its_made": "Beetroots are smoked over applewood for 40 minutes, then blended with tahini, lemon, roasted garlic, and olive oil. Finished with a dusting of sumac and a drizzle of herb oil.",
            "taste_profile": "Earthy, slightly sweet, smoky with a tangy sumac finish. Creamy and smooth.",
            "popularity": 4.1,
            "popularity_note": "Vegan favorite. Often ordered as a table share.",
            "dietary": ["vegan", "gluten-free-option"],
            "spice_level": "none",
            "available": True,
        },
    ],
    "mains": [
        {
            "id": "M01",
            "name": "Butter Chicken",
            "price": 520,
            "currency": "INR",
            "serving": "serves 1-2, with choice of bread or rice",
            "description": "The classic. Tandoori chicken in a velvety tomato-butter-cashew gravy. Our version since 2019.",
            "how_its_made": "Chicken legs are marinated in yogurt and spices, charred in tandoor. The gravy is slow-cooked tomatoes with cashew paste, butter, cream, dried fenugreek (kasuri methi), and a touch of honey. Simmered together for 20 minutes.",
            "taste_profile": "Rich, creamy, mildly sweet with a tomato tang. The kasuri methi gives that signature earthy aroma. Not spicy at all — pure comfort.",
            "popularity": 4.9,
            "popularity_note": "Our #1 seller. Every table orders this. Literally.",
            "dietary": ["non-vegetarian", "contains-dairy", "contains-nuts"],
            "spice_level": "mild",
            "available": True,
        },
        {
            "id": "M02",
            "name": "Rogan Josh",
            "price": 580,
            "currency": "INR",
            "serving": "serves 1-2, with choice of bread or rice",
            "description": "Slow-braised lamb shanks in a Kashmiri chili and fennel gravy. Deeply aromatic, zero shortcuts.",
            "how_its_made": "Lamb shanks are seared and then braised for 3 hours in a gravy of Kashmiri red chilies (deseeded for color, not heat), fennel seeds, dry ginger powder, yogurt, and whole spices. No tomato — purely traditional.",
            "taste_profile": "Deep, complex, warming. The Kashmiri chilies give a gorgeous red color and fruity warmth without burn. Fennel adds sweetness. Fall-off-the-bone tender.",
            "popularity": 4.7,
            "popularity_note": "The dish that gets us 5-star reviews. Takes 3 hours to cook — we start at noon for dinner service.",
            "dietary": ["non-vegetarian", "contains-dairy"],
            "spice_level": "medium",
            "available": True,
        },
        {
            "id": "M03",
            "name": "Dal Makhani",
            "price": 380,
            "currency": "INR",
            "serving": "serves 1-2, with choice of bread or rice",
            "description": "Black lentils slow-cooked overnight with butter, cream, and tomato. 24-hour recipe.",
            "how_its_made": "Whole black urad dal and rajma are soaked overnight, then slow-cooked for 24 hours on low flame with tomato puree, ginger, garlic, butter, and cream. Finished with kasuri methi and a butter pat on top.",
            "taste_profile": "Incredibly creamy, smoky, earthy. The overnight cooking breaks down the lentils into a thick, luxurious gravy. Mild and deeply satisfying.",
            "popularity": 4.7,
            "popularity_note": "Every vegetarian's go-to. Many non-veg customers order this alongside their meat dish.",
            "dietary": ["vegetarian", "contains-dairy"],
            "spice_level": "mild",
            "available": True,
        },
        {
            "id": "M04",
            "name": "Hyderabadi Chicken Biryani",
            "price": 480,
            "currency": "INR",
            "serving": "individual pot, serves 1",
            "description": "Dum-cooked basmati with chicken, saffron, fried onions, and mint. Sealed and slow-cooked in its own steam.",
            "how_its_made": "Chicken is marinated in yogurt and biryani masala. Parboiled aged basmati is layered with the chicken, saffron milk, fried birista onions, mint, and ghee. The pot (handi) is sealed with dough and dum-cooked for 45 minutes.",
            "taste_profile": "Fragrant, each grain separate. The saffron and mint hit first, then warm spices. Chicken is fall-apart tender. The bottom layer (tah dig) is crispy.",
            "popularity": 4.5,
            "popularity_note": "Friday special — sells out by 9 PM. Order early.",
            "dietary": ["non-vegetarian", "contains-dairy"],
            "spice_level": "medium",
            "available": True,
        },
        {
            "id": "M05",
            "name": "Paneer Lababdar",
            "price": 420,
            "currency": "INR",
            "serving": "serves 1-2, with choice of bread or rice",
            "description": "Paneer in a rich, spiced tomato-onion gravy with a cashew cream finish.",
            "how_its_made": "Paneer cubes are lightly fried. The gravy is onions, tomatoes, cashews, and whole spices slow-cooked and blended smooth. Finished with cream, butter, and dried fenugreek.",
            "taste_profile": "Creamy, tangy, and lightly spiced. Richer than paneer butter masala. The cashew gives it body.",
            "popularity": 4.3,
            "popularity_note": "Solid vegetarian main. Pairs perfectly with garlic naan.",
            "dietary": ["vegetarian", "contains-dairy", "contains-nuts"],
            "spice_level": "mild",
            "available": True,
        },
        {
            "id": "M06",
            "name": "Grilled Sea Bass",
            "price": 780,
            "currency": "INR",
            "serving": "single fillet with sides",
            "description": "Pan-seared sea bass with coconut-curry sauce, crispy okra, and lemon rice.",
            "how_its_made": "Fresh sea bass fillet is seasoned with turmeric and sea salt, pan-seared skin-side down until crispy. Served over lemon rice with a Kerala-style coconut curry sauce and fried okra chips.",
            "taste_profile": "Delicate, flaky fish with crispy skin. The coconut sauce is light and fragrant — not heavy. Okra adds crunch.",
            "popularity": 4.2,
            "popularity_note": "Our premium seafood option. Health-conscious regulars love this.",
            "dietary": ["non-vegetarian", "gluten-free", "contains-fish"],
            "spice_level": "mild",
            "available": True,
        },
    ],
    "breads": [
        {"id": "B01", "name": "Butter Naan", "price": 80, "serving": "1 piece", "available": True},
        {"id": "B02", "name": "Garlic Naan", "price": 100, "serving": "1 piece", "available": True},
        {"id": "B03", "name": "Laccha Paratha", "price": 90, "serving": "1 piece", "available": True},
        {"id": "B04", "name": "Tandoori Roti", "price": 50, "serving": "1 piece", "available": True},
        {"id": "B05", "name": "Cheese Naan", "price": 120, "serving": "1 piece", "available": True},
    ],
    "rice": [
        {"id": "R01", "name": "Steamed Basmati", "price": 150, "serving": "1 plate", "available": True},
        {"id": "R02", "name": "Jeera Rice", "price": 180, "serving": "1 plate", "available": True},
        {"id": "R03", "name": "Saffron Pulao", "price": 220, "serving": "1 plate", "available": True},
    ],
    "desserts": [
        {
            "id": "D01",
            "name": "Gulab Jamun Cheesecake",
            "price": 350,
            "currency": "INR",
            "serving": "1 slice",
            "description": "Our signature fusion dessert. New York cheesecake base with gulab jamun pieces, cardamom, and rose syrup drizzle.",
            "how_its_made": "Classic baked cheesecake with cream cheese and cardamom. Warm gulab jamuns are folded in before baking. Finished with a rose and saffron syrup drizzle.",
            "taste_profile": "Creamy, dense cheesecake meets syrupy sweetness of gulab jamun. The cardamom ties it together. Not too sweet.",
            "popularity": 4.8,
            "popularity_note": "Instagram famous. People come just for this.",
            "dietary": ["vegetarian", "contains-dairy", "contains-gluten"],
            "spice_level": "none",
            "available": True,
        },
        {
            "id": "D02",
            "name": "Smoked Chocolate Brownie",
            "price": 300,
            "currency": "INR",
            "serving": "1 piece with vanilla ice cream",
            "description": "Dense dark chocolate brownie lightly smoked over hickory, served warm with vanilla bean ice cream.",
            "how_its_made": "70% dark chocolate brownie batter is poured into a pan, cold-smoked with hickory chips for 10 minutes before baking. Served warm with a scoop of house-made vanilla ice cream.",
            "taste_profile": "Rich, fudgy, with a subtle smokiness that surprises you. The ice cream balances the intensity.",
            "popularity": 4.5,
            "popularity_note": "Perfect end to a meal. The smoke element is unique — people always ask how we do it.",
            "dietary": ["vegetarian", "contains-dairy", "contains-gluten"],
            "spice_level": "none",
            "available": True,
        },
        {
            "id": "D03",
            "name": "Mango Phirni",
            "price": 220,
            "currency": "INR",
            "serving": "1 clay pot",
            "description": "Traditional rice pudding with Alphonso mango, served chilled in a clay pot.",
            "how_its_made": "Basmati rice is ground to a paste, slow-cooked in full-fat milk with sugar and cardamom until thick. Alphonso mango puree is folded in. Set in clay pots and chilled for 4 hours. Topped with pistachios.",
            "taste_profile": "Cool, creamy, subtly grainy from the rice. The mango is sweet and aromatic. Light compared to other desserts.",
            "popularity": 4.3,
            "popularity_note": "Seasonal — only when Alphonso mangoes are available (April-June). Regulars wait all year for this.",
            "dietary": ["vegetarian", "contains-dairy", "contains-nuts", "gluten-free"],
            "spice_level": "none",
            "available": True,
        },
    ],
    "beverages": [
        {"id": "BV01", "name": "Masala Chai", "price": 120, "serving": "1 cup (200ml)", "available": True},
        {"id": "BV02", "name": "Fresh Lime Soda", "price": 150, "serving": "1 glass (300ml)", "available": True},
        {"id": "BV03", "name": "Mango Lassi", "price": 180, "serving": "1 glass (300ml)", "available": True},
        {"id": "BV04", "name": "Rose Sharbat", "price": 160, "serving": "1 glass (300ml)", "available": True},
        {"id": "BV05", "name": "Cold Coffee", "price": 200, "serving": "1 glass (350ml)", "available": True},
        {"id": "BV06", "name": "Bottled Water", "price": 50, "serving": "500ml", "available": True},
    ],
}


def get_full_menu_text() -> str:
    """Return the full menu as formatted text for the agent's context."""
    lines = []
    for category, items in MENU.items():
        lines.append(f"\n{'=' * 40}")
        lines.append(f"  {category.upper()}")
        lines.append(f"{'=' * 40}")
        for item in items:
            lines.append(f"\n[{item['id']}] {item['name']} — ₹{item['price']} ({item['serving']})")
            if "description" in item:
                lines.append(f"  {item['description']}")
            if "taste_profile" in item:
                lines.append(f"  Taste: {item['taste_profile']}")
            if "popularity" in item:
                lines.append(f"  Rating: {'★' * int(item['popularity'])}{'☆' * (5 - int(item['popularity']))} ({item['popularity']}/5) — {item.get('popularity_note', '')}")
            if "spice_level" in item:
                lines.append(f"  Spice: {item['spice_level']}")
            if "dietary" in item:
                lines.append(f"  Dietary: {', '.join(item['dietary'])}")
    return "\n".join(lines)


def find_dish(query: str) -> list[dict]:
    """Search the menu by name or ID (case-insensitive)."""
    query_lower = query.lower()
    results = []
    for items in MENU.values():
        for item in items:
            if query_lower in item["name"].lower() or query_lower == item["id"].lower():
                results.append(item)
    return results
