# main.py - RULE-BASED PARSER FOR CLEAN OUTPUT

from fastapi import FastAPI, HTTPException, Depends, status, File, UploadFile
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
import httpx
from bs4 import BeautifulSoup
from io import BytesIO
from pypdf import PdfReader
from datetime import datetime
import re
from urllib.parse import urljoin
from typing import Optional, Dict, Any, List

# --- Configuration ---
BASE_URL = "https://www.da.gov.ph"
TARGET_URL = "https://www.da.gov.ph/price-monitoring/"
SHARED_SECRET = "Jeremiah_Madronio_API_Key_82219800JeremiahPux83147"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9',
    'Connection': 'keep-alive'
}

# --- DTOs ---
class PriceRow(BaseModel):
    category: str = Field(..., description="Clean category name")
    commodity: str = Field(..., description="Normalized commodity name")
    origin: Optional[str] = Field(None, description="Local or Imported")
    unit: Optional[str] = Field(None, description="kg, pc, or L")
    price: Optional[float] = Field(None, description="Price per unit")

class PdfResponseStructured(BaseModel):
    status: str
    date_processed: Optional[str] = None
    original_url: str
    covered_markets: List[str]
    price_data: List[PriceRow]

class ScrapeRequest(BaseModel):
    target_url: str = Field(TARGET_URL)

# --- App & Security ---
app = FastAPI(title="DA Price Index Scraper (Rule-Based)", version="5.0.0")
api_key_header = APIKeyHeader(name="X-Internal-Secret", auto_error=False)

def verify_internal_access(x_internal_secret: str = Depends(api_key_header)):
    if x_internal_secret == SHARED_SECRET:
        return True
    raise HTTPException(status_code=401, detail="Unauthorized")

# --- Categories ---
KNOWN_CATEGORIES = [
    "IMPORTED COMMERCIAL RICE", "LOCAL COMMERCIAL RICE", "CORN PRODUCTS",
    "FISH PRODUCTS", "BEEF MEAT PRODUCTS", "PORK MEAT PRODUCTS",
    "OTHER LIVESTOCK MEAT PRODUCTS", "POULTRY PRODUCTS",
    "LOWLAND VEGETABLES", "HIGHLAND VEGETABLES", "SPICES",
    "FRUITS", "OTHER BASIC COMMODITIES"
]

# --- Core Logic ---

def parse_date_from_filename(filename: str) -> Optional[datetime]:
    match = re.search(r"([A-Za-z]+-\d{1,2}-\d{4})", filename)
    if not match: return None
    date_str = match.group(1)
    for fmt in ["%B-%d-%Y", "%b-%d-%Y", "%B-%#d-%Y", "%b-%#d-%Y"]:
        try: return datetime.strptime(date_str, fmt)
        except ValueError: continue
    return None

def extract_pdf_content(pdf_bytes: bytes) -> str:
    pdf_file = BytesIO(pdf_bytes)
    reader = PdfReader(pdf_file)
    text = ""
    for page in reader.pages:
        extracted = page.extract_text()
        if extracted: text += f"\n{extracted}\n"
    return text

def normalize_commodity_name(raw_name: str, category: str) -> str:
    """
    Applies strict mapping rules to standardize names based on user requirements.
    """
    # Standardize raw input
    name_clean = re.sub(r'[\x00-\x1F\x7F-\x9F]', '', raw_name)
    name_clean = " ".join(name_clean.split())
    upper_name = name_clean.upper()
    upper_cat = category.upper()

    # --- RULE SET: SPECIFIC COMMODITIES ---

    # 1. CORN Rules (Strict)
    if "CORN" in upper_cat:
        if "GRITS" in upper_name:
            if "WHITE" in upper_name: return "Corn Grits White"
            if "YELLOW" in upper_name: return "Corn Grits Yellow"
            if "FEED GRADE" in upper_name: return "Corn Grits Feed Grade"
        if "CRACKED" in upper_name: return "Corn Cracked Yellow"
        if "COB" in upper_name:
            if "WHITE" in upper_name or "GLUTINOUS" in upper_name: return "Corn Cob White"
            if "YELLOW" in upper_name or "SWEET" in upper_name: return "Corn Cob Yellow"

    # 2. RICE Rules
    if "RICE" in upper_cat:
        if "SPECIAL" in upper_name: return "Special White Rice"
        if "PREMIUM" in upper_name: return "Premium Rice"
        if "WELL MILLED" in upper_name: return "Well Milled Rice"
        if "REGULAR MILLED" in upper_name: return "Regular Milled Rice"
        if "GLUTINOUS" in upper_name: return "Glutinous Rice"
        if "JASPONICA" in upper_name or "JAPONICA" in upper_name: return "Jasponica Rice"
        if "BASMATI" in upper_name: return "Basmati Rice"

    # 3. VEGETABLE Variants (Pull variant from parens)
    # e.g. "Bell Pepper (Red)" -> "Bell Pepper Red"
    if "VEGETABLES" in upper_cat or "SPICES" in upper_cat:
        if "BELL PEPPER" in upper_name:
            if "RED" in upper_name: return "Bell Pepper Red"
            if "GREEN" in upper_name: return "Bell Pepper Green"
        if "CABBAGE" in upper_name:
            if "SCORPIO" in upper_name: return "Cabbage Scorpio"
            if "RARE BALL" in upper_name: return "Cabbage Rare Ball"
            if "WONDER BALL" in upper_name: return "Cabbage Wonder Ball"
        if "ONION" in upper_name:
            if "RED" in upper_name: return "Red Onion"
            if "WHITE" in upper_name: return "White Onion"
        if "CHILLI" in upper_name:
            if "RED" in upper_name or "TINGALA" in upper_name: return "Chilli Red"
            if "GREEN" in upper_name or "PANIGANG" in upper_name: return "Chilli Green"

    # 4. FISH Rules
    if "FISH" in upper_cat:
        if "BANGUS" in upper_name: return "Bangus"
        if "TILAPIA" in upper_name: return "Tilapia"
        if "GALUNGGONG" in upper_name: return "Galunggong"
        if "ALUMAHAN" in upper_name: return "Alumahan"
        if "SQUID" in upper_name: return "Squid"
        if "SALMON BELLY" in upper_name: return "Salmon Belly"
        if "SALMON HEAD" in upper_name: return "Salmon Head"
        if "PAMPANO" in upper_name: return "Pampano"

    # 5. MEAT Rules
    if "MEAT" in upper_cat or "POULTRY" in upper_cat:
        if "WHOLE CHICKEN" in upper_name: return "Whole Chicken"
        if "CHICKEN EGG" in upper_name: return "Chicken Egg"
        if "BEEF BRISKET" in upper_name: return "Beef Brisket"
        if "PORK BELLY" in upper_name: return "Pork Belly"
        if "PORK CHOP" in upper_name: return "Pork Chop"

    # 6. OTHER BASICS
    if "OTHER BASIC" in upper_cat:
        if "COOKING OIL" in upper_name:
            if "PALM" in upper_name: return "Cooking Oil (Palm)"
            if "COCONUT" in upper_name: return "Cooking Oil (Coconut)"
            # Handle generic/brands by falling back to generic names
            return "Cooking Oil"
        if "SUGAR" in upper_name:
            if "REFINED" in upper_name: return "Sugar (Refined)"
            if "WASHED" in upper_name: return "Sugar (Washed)"
            if "BROWN" in upper_name: return "Sugar (Brown)"
        if "SALT" in upper_name:
            if "IODIZED" in upper_name: return "Salt (Iodized)"
            if "ROCK" in upper_name: return "Salt (Rock)"

    # --- FALLBACK CLEANING (If no specific rule matched) ---
    # Remove contents in parentheses if they look like specs/units
    name = re.sub(r'\((.*?)\)', '', name_clean)

    # Remove Brands and Noise
    remove_words = [
        "Magnolia", "Bounty Fresh", "Unbranded", "Fresh", "Fully Dressed",
        "Jolly Brand", "Jolly", "Palm Olein", "Spring", "Minola", "Brand",
        "Local", "Imported", "frozen", "chilled", "whole round", "medium", "large", "small",
        "lean meat", "tapadera", "meat with bones", "food grade", "feed grade"
    ]
    for word in remove_words:
        name = re.sub(rf'\b{word}\b', '', name, flags=re.IGNORECASE)

    # Remove units from name
    name = re.sub(r'\d+[-\s]*\d*\s*(pcs|kg|g|ml|liter|bottle).*', '', name, flags=re.IGNORECASE)

    # Final whitespace clean
    return " ".join(name.split()).strip(" -,")

def determine_origin(raw_line: str, category: str) -> str:
    """Detects Local vs Imported from line text or category."""
    line_upper = raw_line.upper()
    cat_upper = category.upper()

    if "IMPORTED" in line_upper or "IMPORTED" in cat_upper:
        return "Imported"
    # Assume Local if not Imported, unless unspecified
    return "Local"

def determine_unit(raw_line: str, category: str) -> Optional[str]:
    """Decides unit based on line context."""
    line_lower = raw_line.lower()

    if "bottle" in line_lower or "liter" in line_lower or "ml" in line_lower:
        return "L"
    if "egg" in category.lower() or "pc" in line_lower:
        return "pc"
    if any(x in line_lower for x in ["kg", "kilo", "broken", "meat", "fish", "vegetable", "fruit", "spice", "sugar", "salt", "corn"]):
        return "kg"
    return None

def parse_smart_row(line: str, current_category: str) -> Optional[PriceRow]:
    line = line.strip()

    # 1. Find Price
    price_match = re.search(r'(?:^|\s)(\d{1,3}(?:,\d{3})*\.\d{2}|\$n/a\$|-)\s*$', line)
    if not price_match: return None

    price_str = price_match.group(1).replace(',', '')
    raw_name_part = line[:price_match.start()].strip()

    # 2. Determine Origin
    origin = determine_origin(raw_name_part, current_category)

    # 3. Normalize Commodity Name (The Rule-Based Logic)
    clean_name = normalize_commodity_name(raw_name_part, current_category)

    if len(clean_name) < 2: return None

    # 4. Determine Unit
    unit = determine_unit(raw_name_part, current_category)

    # 5. Convert Price
    final_price = None
    try:
        if price_str not in ['-', '$n/a$']:
            final_price = float(price_str)
    except:
        pass

    # 6. Clean Category (Remove LOCAL/IMPORTED from label for cleaner DB storage)
    clean_cat = current_category.replace("IMPORTED ", "").replace("LOCAL ", "").strip()

    return PriceRow(
        category=clean_cat,
        commodity=clean_name,
        origin=origin,
        unit=unit,
        price=final_price
    )

def parse_text_to_json(raw_text: str) -> Dict[str, Any]:
    lines = raw_text.split('\n')
    price_data_list = []
    current_category = "UNKNOWN"
    market_list = []

    # Market Extraction
    market_match = re.search(r"(?:d\)|Covered markets:)\s*(1\..+?)(?:Page|\Z)", raw_text, re.DOTALL | re.IGNORECASE)
    if market_match:
        raw_block = market_match.group(1)
        raw_markets = re.split(r'\s*\d+\.\s*', raw_block)
        market_list = [
            re.sub(r'[\n\r]', ' ', m).strip()
            for m in raw_markets if m.strip() and len(m) > 3
        ]
        market_list = list(dict.fromkeys(market_list))

    # Row Processing
    for line in lines:
        line = line.strip()
        if not line: continue

        # Category Detection
        is_category = False
        for cat in KNOWN_CATEGORIES:
            if cat in line.upper():
                current_category = cat
                is_category = True
                break
        if is_category: continue

        if any(x in line for x in ["Source:", "Note:", "Prevailing", "Retail Price", "Page", "Department of"]):
            continue

        if current_category != "UNKNOWN":
            row = parse_smart_row(line, current_category)
            if row:
                # Simple Duplicate Check (Same Name + Same Origin = Duplicate)
                is_duplicate = False
                for existing in price_data_list:
                    if existing.category == row.category and existing.commodity == row.commodity and existing.origin == row.origin:
                        # Keep the one with a price if the existing one is null
                        if existing.price is None and row.price is not None:
                            existing.price = row.price
                        is_duplicate = True
                        break

                if not is_duplicate:
                    price_data_list.append(row)

    return {
        "covered_markets": market_list,
        "price_data": price_data_list
    }

# --- ENDPOINTS ---

@app.post("/api/scrape-new-pdf", response_model=PdfResponseStructured, dependencies=[Depends(verify_internal_access)])
async def scrape_new_pdf_data(request: ScrapeRequest):
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(request.target_url, headers=HEADERS)
            resp.raise_for_status()
        except Exception as e:
            raise HTTPException(500, f"Fetch failed: {str(e)}")

        soup = BeautifulSoup(resp.text, 'lxml')
        links = soup.find_all('a', href=re.compile(r'(Daily-Price-Index|DPI).*?\.pdf$', re.IGNORECASE))

        if not links:
            raise HTTPException(404, "No Daily Price Index PDFs found.")

        newest_link = None
        latest_date = datetime.min

        for link in links:
            href = link.get('href')
            f_name = href.split('/')[-1]
            f_date = parse_date_from_filename(f_name)

            if f_date and f_date > latest_date:
                latest_date = f_date
                newest_link = {
                    'href': urljoin(BASE_URL, href),
                    'date_str': f_date.strftime("%Y-%m-%d")
                }

        if not newest_link:
            raise HTTPException(404, "Could not determine dates from PDF links.")

        print(f"Processing: {newest_link['href']}")
        pdf_resp = await client.get(newest_link['href'], headers=HEADERS)
        content = extract_pdf_content(pdf_resp.content)
        data = parse_text_to_json(content)

        return PdfResponseStructured(
            status="Success",
            date_processed=newest_link['date_str'],
            original_url=newest_link['href'],
            covered_markets=data['covered_markets'],
            price_data=data['price_data']
        )

@app.post("/api/extract-manual", response_model=PdfResponseStructured, dependencies=[Depends(verify_internal_access)])
async def extract_manual_pdf(file: UploadFile = File(...)):
    if file.content_type != 'application/pdf':
        raise HTTPException(400, "File must be PDF")

    content = await file.read()
    text = extract_pdf_content(content)
    date_str = datetime.now().strftime("%Y-%m-%d")
    data = parse_text_to_json(text)

    return PdfResponseStructured(
        status="Success (Manual)",
        date_processed=date_str,
        original_url=f"Manual: {file.filename}",
        covered_markets=data['covered_markets'],
        price_data=data['price_data']
    )

@app.get("/")
def root():
    return {"message": "Smart DA Price Scraper is Running"}