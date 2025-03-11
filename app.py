from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from pony import orm
import json

# Set up the Database
db = orm.Database()
db.bind(provider='sqlite', filename='database6.sqlite', create_db=True)

class BookPrice(db.Entity):
    book_name = orm.Required(str)
    isbn = orm.Optional(str, nullable=True)
    author = orm.Optional(str, nullable=True)
    image_url = orm.Optional(str, nullable=True)
    website = orm.Required(str)
    price = orm.Required(float)
    date_created = orm.Required(datetime)

db.generate_mapping(create_tables=True)

app = Flask(__name__)

# Scraping functions
def amazon(session, headers, book_name):
    url = "https://amzn.in/d/ctd5cdW"
    resp = session.get(url, headers=headers)
    soup = BeautifulSoup(resp.text, "html.parser")

    whole_price_element = soup.select_one("span.a-price-whole")
    fraction_price_element = soup.select_one("span.a-price-fraction")
    author_element = soup.select_one("span.author a")

    # Extract Image URL
    image_element = soup.find("img", id="landingImage") or soup.find("img", class_="frontImage")
    image_url = image_element['src'] if image_element else "Image Not Found"

    # Extract ISBN-13
    isbn = None
    product_details = soup.find("div", {"id": "detailBullets_feature_div"})
    if product_details:
        for li in product_details.find_all("li"):
            text = li.get_text(strip=True)
            if "ISBN-13" in text:
                isbn = text.split(":")[-1].strip()
                break

    if not isbn:
        product_table = soup.find("table", {"id": "productDetailsTable"})
        if product_table:
            for row in product_table.find_all("tr"):
                text = row.get_text(strip=True)
                if "ISBN-13" in text:
                    isbn = text.split(":")[-1].strip()
                    break

    if whole_price_element is None:
        return book_name, isbn, None, image_url, "amazon", 0.0

    whole_price = whole_price_element.text.replace(",", "").strip()
    fraction_price = fraction_price_element.text.strip() if fraction_price_element else "00"
    price_text = f"{whole_price}.{fraction_price}"

    try:
        price = float(price_text)
    except ValueError:
        price = 0.0

    author = author_element.text.strip() if author_element else "Unknown"

    return book_name, isbn, author, image_url, "amazon", price

def bookswagon(session, headers, book_name):
    url = "https://www.bookswagon.com/book/little-women-louisa-may-alcott/9780099572961"
    resp = session.get(url, headers=headers)
    soup = BeautifulSoup(resp.text, "html.parser")

    price_element = soup.find("label", id="ctl00_phBody_ProductDetail_lblourPrice")

    isbn_element = None
    for li in soup.find_all("li"):
        if "ISBN-13:" in li.text:
            isbn_element = li.text.split("ISBN-13:")[-1].strip()
            break
    isbn = isbn_element if isbn_element else "Unknown"

    author_element = soup.select_one("label#ctl00_phBody_ProductDetail_lblAuthor1 a")
    author = author_element.text.strip() if author_element else "Unknown"

    # Extract Image URL
    image_element = soup.find("img", src=True)
    image_url = image_element['src'] if image_element else "Image Not Found"

    if price_element is None:
        return book_name, None, None, image_url, "bookswagon", 0.0

    price_text = price_element.text.replace("₹", "").replace(",", "").strip()
    
    try:
        price = float(price_text)
    except ValueError:
        price = 0.0

    return book_name, isbn, author, image_url, "bookswagon", price

def kitabay(session, headers, book_name):
    url = "https://kitabay.com/products/little-women-4?_pos=1&_sid=3ea41e284&_ss=r"
    resp = session.get(url, headers=headers)
    soup = BeautifulSoup(resp.text, "html.parser")

    price_element = soup.find("span", class_="product__price--sale")

    # Extract Image URL
    image_element = soup.find("img", class_="object-cover")
    image_url = image_element['src'] if image_element else "Image Not Found"

    author_element = soup.find("p", string=lambda text: text and "Author -" in text)
    author = author_element.text.replace("Author -", "").strip() if author_element else "Unknown"

    isbn_element = soup.find("p", string=lambda text: text and "ISBN:" in text)
    isbn = isbn_element.text.replace("ISBN:", "").strip() if isbn_element else "Unknown"

    if price_element is None:
        return book_name, None, None, image_url, "kitabay", 0.0

    price_text = price_element.text.replace("Rs.", "").replace(",", "").strip()
    
    try:
        price = float(price_text)
    except ValueError:
        price = 0.0

    return book_name, isbn, author, image_url, "kitabay", price

# Routes
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/book/<book_id>')
def book_detail(book_id):
    return render_template('book_detail.html', book_id=book_id)

@app.route('/search')
def search():
    query = request.args.get('query', '')
    return render_template('search.html', query=query)

# API Endpoints
@app.route('/api/search', methods=['GET'])
def api_search():
    query = request.args.get('query', '')
    
    if not query:
        return jsonify({"error": "Query parameter is required"}), 400
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.5060.134 Safari/537.36'
    }
    session = requests.Session()

    # Fetch data from all sources
    scraped_data = [
        amazon(session, headers, query),
        bookswagon(session, headers, query),
        kitabay(session, headers, query)
    ]

    # Sort by price (cheapest first)
    sorted_data = sorted(scraped_data, key=lambda x: x[5])

    # Insert data into the database
    with orm.db_session:
        for item in sorted_data:
            BookPrice(
                book_name=item[0],
                isbn=item[1],
                author=item[2],
                image_url=item[3],
                website=item[4],
                price=item[5],
                date_created=datetime.now()
            )

    # Format the data for the API response
    results = []
    for i, item in enumerate(sorted_data):
        results.append({
            "id": str(i + 1),  # Generate an ID for the book
            "book_name": item[0],
            "isbn": item[1],
            "author": item[2],
            "image_url": item[3],
            "website": item[4],
            "price": item[5],
            "date_created": datetime.now().isoformat()
        })

    return jsonify(results)

@app.route('/api/book/<book_id>', methods=['GET'])
def api_book_detail(book_id):
    # In a real application, you would query the database
    # For this example, we'll return mock data
    book_name = "Little Women" if book_id == "1" else "One Indian Girl"
    
    # Query the database for prices of this book
    with orm.db_session:
        prices = list(BookPrice.select(lambda b: b.book_name == book_name)[:])
        
        if not prices:
            # If no prices in DB, return mock data
            return jsonify({
                "book_name": book_name,
                "isbn": "9781234567890",
                "author": "Louisa May Alcott" if book_id == "1" else "Chetan Bhagat",
                "image_url": "https://source.unsplash.com/random/200x300/?book",
                "prices": [
                    {
                        "website": "amazon",
                        "price": 250.0,
                        "date_created": datetime.now().isoformat()
                    },
                    {
                        "website": "bookswagon",
                        "price": 275.0,
                        "date_created": datetime.now().isoformat()
                    },
                    {
                        "website": "kitabay",
                        "price": 260.0,
                        "date_created": datetime.now().isoformat()
                    }
                ]
            })
        
        # Convert database entities to dictionaries
        result = {
            "book_name": prices[0].book_name,
            "isbn": prices[0].isbn,
            "author": prices[0].author,
            "image_url": prices[0].image_url,
            "prices": []
        }
        
        for price in prices:
            result["prices"].append({
                "website": price.website,
                "price": price.price,
                "date_created": price.date_created.isoformat()
            })
        
        return jsonify(result)

@app.route('/api/featured', methods=['GET'])
def api_featured_books():
    # Return mock featured books
    return jsonify([
        {
            "id": "1",
            "book_name": "Three Thousand Stitches",
            "author": "Sudha Murty",
            "image_url": "https://source.unsplash.com/random/200x300/?book",
            "websites": ["amazon", "bookswagon", "kitabay"],
            "lowest_price": 250.00
        },
        {
            "id": "2",
            "book_name": "One Indian Girl",
            "author": "Chetan Bhagat",
            "image_url": "https://source.unsplash.com/random/200x300/?novel",
            "websites": ["amazon", "bookswagon", "kitabay"],
            "lowest_price": 199.00
        },
        {
            "id": "3",
            "book_name": "Little Women",
            "author": "Louisa May Alcott",
            "image_url": "https://source.unsplash.com/random/200x300/?fiction",
            "websites": ["amazon", "bookswagon", "kitabay"],
            "lowest_price": 180.00
        }
    ])

if __name__ == '__main__':
    app.run(debug=True, port=5000)

