from fastapi import FastAPI, Query, HTTPException, Request
from pydantic import BaseModel
import asyncpg
import asyncio
import json
from playwright.async_api import async_playwright
import hashlib
import os

app = FastAPI()

DATABASE_URL = "postgresql://user:password@host/dbname"
OWNER_KEY = "AZKX-KW3D-9FWW"  # Clé Owner prédéfinie

async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id SERIAL PRIMARY KEY,
            user TEXT NOT NULL,
            key_hash TEXT UNIQUE NOT NULL,
            active BOOLEAN DEFAULT TRUE
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id SERIAL PRIMARY KEY,
            apikey TEXT,
            ip TEXT,
            search TEXT,
            source TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.close()

@app.on_event("startup")
async def startup():
    await init_db()

def hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()

async def check_api_key(apikey: str):
    if apikey == OWNER_KEY:
        return True
    
    conn = await asyncpg.connect(DATABASE_URL)
    key_hash = hash_key(apikey)
    row = await conn.fetchrow("SELECT active FROM api_keys WHERE key_hash = $1", key_hash)
    await conn.close()

    if row and row["active"]:
        return True
    return False

async def log_search(apikey, ip, search, source):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("INSERT INTO logs (apikey, ip, search, source) VALUES ($1, $2, $3, $4)", apikey, ip, search, source)
    await conn.close()

async def search_terabox(query: str, source: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://www.terabox.com/")

        try:
            await page.fill("input[name='email']", "ton_email")
            await page.fill("input[name='password']", "ton_mot_de_passe")
            await page.click("button[type='submit']")
            await asyncio.sleep(5)

            await page.goto(f"https://www.terabox.com/{source}")
            await asyncio.sleep(3)

            files = await page.evaluate(f"""() => {{
                let results = [];
                document.querySelectorAll(".file-name").forEach(file => {{
                    if (file.innerText.includes("{query}")) {{
                        results.push({{"filename": file.innerText}});
                    }}
                }});
                return results;
            }}""")

            await browser.close()
            return files

        except Exception as e:
            await browser.close()
            return {"error": str(e)}

@app.get("/{category}")
async def search(category: str, query: str = Query(...), key: str = Query(...), request: Request):
    if not await check_api_key(key):
        raise HTTPException(status_code=403, detail="Clé API invalide ou désactivée")

    category_map = {
        "fivem": "FiveM",
        "all": "All",
        "snus": "Snusbase",
        "intelx": "IntelX",
        "nazapi": "NazAPI",
        "gmail": "Gmail"
    }

    if category not in category_map:
        raise HTTPException(status_code=400, detail="Catégorie invalide")

    ip = request.client.host
    results = await search_terabox(query, category_map[category])
    
    await log_search(key, ip, query, category_map[category])

    return {"status": "success", "results": results}

@app.get("/create")
async def create_key(user: str, key: str = Query(...)):
    if key != OWNER_KEY:
        raise HTTPException(status_code=403, detail="Accès refusé")

    new_key = os.urandom(16).hex()
    key_hash = hash_key(new_key)

    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("INSERT INTO api_keys (user, key_hash) VALUES ($1, $2)", user, key_hash)
    await conn.close()

    return {"status": "success", "message": f"Clé API créée pour {user}", "api_key": new_key}

@app.get("/allkeys")
async def get_keys(key: str = Query(...)):
    if key != OWNER_KEY:
        raise HTTPException(status_code=403, detail="Accès refusé")

    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch("SELECT user, active FROM api_keys")
    await conn.close()

    return {"status": "success", "keys": [{"user": row["user"], "active": row["active"]} for row in rows]}

@app.get("/logs")
async def get_logs(key: str = Query(...)):
    if key != OWNER_KEY:
        raise HTTPException(status_code=403, detail="Accès refusé")

    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch("SELECT apikey, ip, search, source, timestamp FROM logs")
    await conn.close()

    return {"status": "success", "logs": [{"apikey": row["apikey"], "ip": row["ip"], "search": row["search"], "source": row["source"], "timestamp": row["timestamp"]} for row in rows]}

# Lancer le serveur avec Uvicorn
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
  
