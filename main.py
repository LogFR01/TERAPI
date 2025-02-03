from fastapi import FastAPI, Query, HTTPException, Request
from pydantic import BaseModel
import json, os, hashlib, asyncio, time
from playwright.async_api import async_playwright
import subprocess

app = FastAPI()

OWNER_KEY = "AZKX-KW3D-9FWW"
DATA_PATH = "data"
os.makedirs(DATA_PATH, exist_ok=True)

def load_json(filename):
    path = f"{DATA_PATH}/{filename}.json"
    return json.load(open(path)) if os.path.exists(path) else {}

def save_json(filename, data):
    with open(f"{DATA_PATH}/{filename}.json", "w") as f:
        json.dump(data, f, indent=4)

def hash_key(api_key):
    return hashlib.sha256(api_key.encode()).hexdigest()

def check_api_key(api_key):
    if api_key == OWNER_KEY:
        return True
    keys = load_json("api_keys")
    key_data = keys.get(hash_key(api_key))
    if not key_data or not key_data.get("active"):
        return False
    if key_data["expires_at"] and time.time() > key_data["expires_at"]:
        key_data["active"] = False
        save_json("api_keys", keys)
        return False
    if key_data["remaining_requests"] <= 0:
        key_data["active"] = False
        save_json("api_keys", keys)
        return False
    return True

def install_playwright():
    """Vérifie et installe Playwright + Chromium si nécessaire"""
    try:
        subprocess.run(["playwright", "--version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        print("🔧 Playwright n'est pas installé. Installation en cours...")
        subprocess.run(["playwright", "install", "--with-deps"], check=True)
    except FileNotFoundError:
        print("🔧 Playwright introuvable. Installation en cours...")
        subprocess.run(["pip", "install", "playwright"], check=True)
        subprocess.run(["playwright", "install", "--with-deps"], check=True)

async def log_search(apikey, ip, search, source):
    logs = load_json("logs")
    logs.append({"apikey": apikey, "ip": ip, "search": search, "source": source, "timestamp": int(time.time())})
    save_json("logs", logs)

async def search_terabox(query, source):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://www.terabox.com/")
        try:
    # Remplir les champs de connexion
    await page.fill("input[name='email']", "dkwblinks@gmail.com")
    await page.fill("input[name='password']", "marvine8")
    await page.click("button[type='submit']")
    await asyncio.sleep(5)
    
    error_message = await page.query_selector("div.error-message")
    if error_message:
        raise Exception("Echec de la connexion à Terabox")
    
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
    print(f"Erreur lors de la connexion ou de l'extraction des fichiers : {e}")
    return []

@app.get("/")
async def welcome():
    return {"message": "Bienvenue sur TERAPI | ZOIDBERG : L'API de recherche Terabox ! Pour rechercher, utilisez la route '/{category}' avec les paramètres 'query' et 'key'."}

@app.get("/{category}")
async def search(category: str, request: Request, query: str = Query(...), key: str = Query(...)):
    if not check_api_key(key):
        raise HTTPException(status_code=403, detail="Clé API invalide ou expirée")
    category_map = {"fivem": "FiveM", "all": "All", "snus": "Snusbase", "intelx": "IntelX", "nazapi": "NazAPI", "gmail": "Gmail"}
    if category not in category_map:
        raise HTTPException(status_code=400, detail="Catégorie invalide")
    ip = request.client.host
    results = await search_terabox(query, category_map[category])
    await log_search(key, ip, query, category_map[category])

    keys = load_json("api_keys")
    keys[hash_key(key)]["remaining_requests"] -= 1
    save_json("api_keys", keys)

    return {"status": "success", "results": results}

@app.get("/create")
async def create_key(user: str, duration: int = Query(...), max_requests: int = Query(...), key: str = Query(...)):
    if key != OWNER_KEY:
        raise HTTPException(status_code=403, detail="Accès refusé")
    new_key = os.urandom(16).hex()
    key_hash = hash_key(new_key)
    keys = load_json("api_keys")
    keys[key_hash] = {
        "user": user,
        "active": True,
        "expires_at": time.time() + duration if duration > 0 else None,
        "remaining_requests": max_requests
    }
    save_json("api_keys", keys)
    return {"status": "success", "api_key": new_key, "expires_in": duration, "max_requests": max_requests}

@app.get("/allkeys")
async def get_keys(key: str = Query(...)):
    if key != OWNER_KEY:
        raise HTTPException(status_code=403, detail="Accès refusé")
    keys = load_json("api_keys")
    return {"status": "success", "keys": [{"user": v["user"], "active": v["active"], "expires_at": v["expires_at"], "remaining_requests": v["remaining_requests"]} for v in keys.values()]}

@app.get("/logs")
async def get_logs(key: str = Query(...)):
    if key != OWNER_KEY:
        raise HTTPException(status_code=403, detail="Accès refusé")
    return {"status": "success", "logs": load_json("logs")}

@app.get("/delete")
async def delete_key(target_key: str = Query(...), key: str = Query(...)):
    if key != OWNER_KEY:
        raise HTTPException(status_code=403, detail="Accès refusé")
    keys = load_json("api_keys")
    target_hash = hash_key(target_key)
    if target_hash not in keys:
        raise HTTPException(status_code=404, detail="Clé introuvable")
    del keys[target_hash]
    save_json("api_keys", keys)
    return {"status": "success", "message": "Clé supprimée"}

@app.get("/deactivate")
async def deactivate_key(target_key: str = Query(...), key: str = Query(...)):
    if key != OWNER_KEY:
        raise HTTPException(status_code=403, detail="Accès refusé")
    keys = load_json("api_keys")
    target_hash = hash_key(target_key)
    if target_hash not in keys:
        raise HTTPException(status_code=404, detail="Clé introuvable")
    keys[target_hash]["active"] = False
    save_json("api_keys", keys)
    return {"status": "success", "message": "Clé désactivée"}

if __name__ == "__main__":
    install_playwright()  # Assure l'installation de Playwright
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
