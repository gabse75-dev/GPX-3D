import streamlit as st
import pandas as pd
import numpy as np
import xml.etree.ElementTree as ET
import math
import json
import requests
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# Configurazione pagina
st.set_page_config(page_title="GPX 3D Alpine Analyzer", layout="wide")

st.title("🏔️ GPX 3D Alpine Analyzer & Technical Route Mapper")
st.write("Analisi avanzata con pacer integrato, rilevamento dei tratti critici, profilo altimetrico e meteo dinamico in quota.")

# --- CALCOLI GEOGRAFICI ---

def calcola_distanza_haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * \
        math.sin(delta_lambda / 2.0) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

def calcola_bearing(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    d_lon = lon2 - lon1
    y = math.sin(d_lon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(d_lon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360

def parse_gpx(file):
    tree = ET.parse(file)
    root = tree.getroot()
    ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
    
    punti = []
    for trkpt in root.findall(f'.//{ns}trkpt'):
        lat = float(trkpt.attrib['lat'])
        lon = float(trkpt.attrib['lon'])
        ele_elem = trkpt.find(f'{ns}ele')
        ele = float(ele_elem.text) if ele_elem is not None else 0.0
        punti.append({'lat': lat, 'lon': lon, 'ele': ele})
    return punti

def analizza_percorso(punti, soglia_pendenza, step_semplificazione=1):
    if step_semplificazione > 1:
        punti = punti[::step_semplificazione]

    features = []
    distanza_cumulata = 0.0
    dislivello_pos = 0.0
    dist_tecnica = 0.0
    
    distanze_punti = [0.0]
    pendenze = [0.0]
    
    for i in range(len(punti) - 1):
        p1, p2 = punti[i], punti[i+1]
        dist = calcola_distanza_haversine(p1['lat'], p1['lon'], p2['lat'], p2['lon'])
        delta_ele = p2['ele'] - p1['ele']
        pendenza = (delta_ele / dist * 100) if dist > 0 else 0.0
        
        distanza_cumulata += dist
        distanze_punti.append(distanza_cumulata)
        pendenze.append(pendenza)
        
        if delta_ele > 0:
            dislivello_pos += delta_ele
            
        # Algoritmo di gradiente di colore dinamico
        pendenza_assoluta = abs(pendenza)
        t = min(pendenza_assoluta / soglia_pendenza, 1.0)
        
        r = int(40 + (255 - 40) * t)
        g = int(200 + (40 - 200) * t)
        b = int(100 + (40 - 100) * t)
        color_hex = f"#{r:02X}{g:02X}{b:02X}"
        
        if pendenza_assoluta >= soglia_pendenza:
            dist_tecnica += dist
            
        features.append({
            "type": "Feature",
            "properties": {
                "color": color_hex,
                "pendenza": round(pendenza, 1),
                "quota": round(p2['ele'], 0),
                "dist": round(dist, 1),
                "index": i
            },
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [p1['lon'], p1['lat'], p1['ele']],
                    [p2['lon'], p2['lat'], p2['ele']]
                ]
            }
        })
            
    df_punti = pd.DataFrame(punti)
    df_punti['distanza_km'] = [d / 1000.0 for d in distanze_punti]
    df_punti['pendenza'] = pendenze
    
    geojson_traccia = {
        "type": "FeatureCollection",
        "features": features
    }
    
    dist_totale = distanza_cumulata
    
    # --- CALCOLO DEI TRATTI CRITICI ---
    tratti_critici = []
    in_tratto = False
    inizio_idx = 0
    lunghezza_tratto = 0.0
    dislivello_tratto = 0.0
    
    for i in range(len(features)):
        prop = features[i]["properties"]
        geom = features[i]["geometry"]
        pendenza_ass = abs(prop["pendenza"])
        
        if pendenza_ass >= soglia_pendenza:
            if not in_tratto:
                in_tratto = True
                inizio_idx = i
                lunghezza_tratto = 0.0
                dislivello_tratto = 0.0
            
            lunghezza_tratto += prop["dist"]
            coor = geom["coordinates"]
            dislivello_tratto += (coor[1][2] - coor[0][2])
        else:
            if in_tratto:
                in_tratto = False
                if lunghezza_tratto >= 150:
                    km_inizio = distanze_punti[inizio_idx] / 1000.0
                    pendenza_media = (dislivello_tratto / lunghezza_tratto) * 100
                    tipo = "Salita" if dislivello_tratto > 0 else "Discesa"
                    tratti_critici.append({
                        "ID": len(tratti_critici) + 1,
                        "Tipo": tipo,
                        "Inizio (Km)": round(km_inizio, 1),
                        "Lunghezza (m)": round(lunghezza_tratto, 0),
                        "Pendenza Media (%)": round(pendenza_media, 1),
                        "Dislivello (m)": round(dislivello_tratto, 0),
                        "lat": df_punti.iloc[inizio_idx]['lat'],
                        "lon": df_punti.iloc[inizio_idx]['lon']
                    })
                    
    if in_tratto and lunghezza_tratto >= 150:
        km_inizio = distanze_punti[inizio_idx] / 1000.0
        pendenza_media = (dislivello_tratto / lunghezza_tratto) * 100
        tipo = "Salita" if dislivello_tratto > 0 else "Discesa"
        tratti_critici.append({
            "ID": len(tratti_critici) + 1,
            "Tipo": tipo,
            "Inizio (Km)": round(km_inizio, 1),
            "Lunghezza (m)": round(lunghezza_tratto, 0),
            "Pendenza Media (%)": round(pendenza_media, 1),
            "Dislivello (m)": round(dislivello_tratto, 0),
            "lat": df_punti.iloc[inizio_idx]['lat'],
            "lon": df_punti.iloc[inizio_idx]['lon']
        })
                    
    return geojson_traccia, dist_totale, dislivello_pos, dist_tecnica, df_punti, tratti_critici

# --- CALCOLO FASCE ALTIMETRICHE ---
def calcola_fasce_altimetriche(df_punti):
    if df_punti.empty or len(df_punti) < 2:
        return pd.DataFrame()
        
    limiti = [
        (-float('inf'), 1000, "Sotto i 1000 m"),
        (1000, 1500, "Tra 1000 m e 1500 m"),
        (1500, 2000, "Tra 1500 m e 2000 m"),
        (2000, 2500, "Tra 2000 m e 2500 m"),
        (2500, 3000, "Tra 2500 m e 3000 m"),
        (3000, 3500, "Tra 3000 m e 3500 m"),
        (3500, 4000, "Tra 3500 m e 4000 m"),
        (4000, float('inf'), "Sopra i 4000 m")
    ]
    
    distanze_fasce = {nome: 0.0 for _, _, nome in limiti}
    
    for i in range(len(df_punti) - 1):
        p1 = df_punti.iloc[i]
        p2 = df_punti.iloc[i+1]
        dist_km = p2['distanza_km'] - p1['distanza_km']
        quota_media = (p1['ele'] + p2['ele']) / 2.0
        
        for min_q, max_q, nome in limiti:
            if min_q <= quota_media < max_q:
                distanze_fasce[nome] += dist_km
                break
                
    tot_dist = sum(distanze_fasce.values())
    
    dati_fasce = []
    for _, _, nome in limiti:
        dist_km = distanze_fasce[nome]
        if tot_dist > 0:
            percentuale = (dist_km / tot_dist) * 100.0
        else:
            percentuale = 0.0
            
        if dist_km > 0.001:
            dati_fasce.append({
                "Fascia Altimetrica": nome,
                "Distanza (Km)": round(dist_km, 2),
                "Percentuale (%)": round(percentuale, 1)
            })
            
    return pd.DataFrame(dati_fasce)

# --- ALGORITMO PACER VIRTUALE (MINETTI / NAISMITH) ---
def calcola_pacer_tabella(df_punti, ore_target):
    if df_punti.empty or ore_target <= 0:
        return pd.DataFrame(), {}
        
    tot_dist_km = df_punti['distanza_km'].max()
    secondi_target = ore_target * 3600
    
    df_punti['km_arrotondato'] = df_punti['distanza_km'].astype(int) + 1
    gruppi = df_punti.groupby('km_arrotondato')
    
    pesi_km = []
    dati_km = []
    
    for km, g in gruppi:
        if len(g) < 2:
            continue
        dist_effettiva = (g['distanza_km'].max() - g['distanza_km'].min())
        if dist_effettiva < 0.1:
            dist_effettiva = 1.0
            
        ele_inizio = g['ele'].iloc[0]
        ele_fine = g['ele'].iloc[-1]
        disl_positivo = max(0, ele_fine - ele_inizio)
        disl_negativo = max(0, ele_inizio - ele_fine)
        
        pendenza_media = ((ele_fine - ele_inizio) / (dist_effettiva * 1000.0)) * 100 if dist_effettiva > 0 else 0
        
        peso_sforzo = dist_effettiva
        if disl_positivo > 0:
            peso_sforzo += (disl_positivo / 100.0)
        if disl_negativo > 0 and pendenza_media < -8:
            peso_sforzo += (disl_negativo / 250.0)
            
        pesi_km.append(peso_sforzo)
        dati_km.append({
            "Km": km,
            "D+": round(disl_positivo, 0),
            "D-": round(disl_negativo, 0),
            "Sforzo": peso_sforzo,
            # Teniamo traccia della coordinata approssimativa di questo chilometro per calcolare il meteo in corsa
            "lat": g['lat'].mean(),
            "lon": g['lon'].mean(),
            "ele": g['ele'].mean()
        })
        
    tot_sforzo = sum(pesi_km)
    if tot_sforzo == 0:
        return pd.DataFrame(), {}
        
    secondi_per_unita = secondi_target / tot_sforzo
    cronologia_cumulata = 0.0
    tabella_pacer = []
    mappa_orari_km = {} # Mappa fondamentale per sapere a che ORA esatta passerai in ciascun chilometro
    
    for item in dati_km:
        secondi_km = item["Sforzo"] * secondi_per_unita
        passo_minuti_decimale = secondi_km / 60.0
        
        minuti = int(passo_minuti_decimale)
        secondi = int((passo_minuti_decimale - minuti) * 60)
        passo_str = f"{minuti:02d}:{secondi:02d} /km"
        
        cronologia_cumulata += secondi_km
        ore_cum = int(cronologia_cumulata / 3600)
        min_cum = int((cronologia_cumulata % 3600) / 60)
        tempo_passaggio = f"{ore_cum:02d}h {min_cum:02d}m"
        
        tabella_pacer.append({
            "Chilometro": f"Km {item['Km']}",
            "Dislivello Salita": f"+{item['D+']:.0f}m",
            "Dislivello Discesa": f"-{item['D-']:.0f}m",
            "Passo Suggerito": passo_str,
            "Tempo Cumulato": tempo_passaggio
        })
        
        # Salviamo la quota, le coordinate e i secondi cumulati per mappare l'ora del passaggio meteo
        mappa_orari_km[item['Km']] = {
            "lat": item["lat"],
            "lon": item["lon"],
            "ele": item["ele"],
            "secondi_da_partenza": cronologia_cumulata
        }
        
    return pd.DataFrame(tabella_pacer), mappa_orari_km

# --- ICONE METEO OPEN-METEO ---
def interpreta_wmo_code(code):
    # Standard WMO Weather Interpretation Codes
    mappa_codici = {
        0: "☀️ Sereno",
        1: "🌤️ Prevalentemente Sereno", 2: "⛅ Poco Nuvoloso", 3: "☁️ Coperto",
        45: "🌫️ Nebbia", 48: "🌫️ Nebbia con Brina",
        51: "🌧️ Pioggerellina leggera", 53: "🌧️ Pioggerellina moderata", 55: "🌧️ Pioggerellina fitta",
        61: "🌧️ Pioggia debole", 63: "🌧️ Pioggia moderata", 65: "🌧️ Pioggia forte",
        71: "🌨️ Neve debole", 73: "🌨️ Neve moderata", 75: "🌨️ Neve forte",
        77: "🌨️ Granelli di neve",
        80: "🌧️ Acquazzone debole", 81: "🌧️ Acquazzone moderato", 82: "🌧️ Acquazzone violento",
        85: "🌨️ Rovescio di neve debole", 86: "🌨️ Rovescio di neve forte",
        95: "⚡ Temporale", 96: "⚡⛈️ Temporale con grandine debole", 99: "⚡⛈️ Temporale con forte grandine"
    }
    return mappa_codici.get(code, "❓ Sconosciuto")

# --- CALCOLO METEO IN CORSA CON GRADIENTE TERMICO REALE (RISOLTO DEFINITIVAMENTE) ---
@st.cache_data(ttl=600)
def scarica_meteo_percorso(lat, lon, data_partenza, mappa_orari, ore_target):
    # Calcoliamo esattamente il giorno d'inizio e fine basandoci sulla durata della corsa
    giorno_inizio_str = data_partenza.strftime("%Y-%m-%d")
    data_fine = data_partenza + timedelta(hours=float(ore_target) + 2) # Aggiungiamo un cuscinetto di 2 ore
    giorno_fine_str = data_fine.strftime("%Y-%m-%d")
    
    # URL preciso con data di inizio, data di fine e fuso orario italiano esplicito
    url = f"https://api.open-meteo.com/en/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m,weather_code,wind_speed_10m&timezone=Europe/Rome&start_date={giorno_inizio_str}&end_date={giorno_fine_str}"
    
    try:
        res = requests.get(url).json()
        if "hourly" not in res:
            return []
            
        times_str = res["hourly"]["time"]
        temps = res["hourly"]["temperature_2m"]
        codes = res["hourly"]["weather_code"]
        winds = res["hourly"]["wind_speed_10m"]
        elevation_modello = res.get("elevation", 500)
        
        # Creiamo un dizionario locale per mappare gli orari ISO8601 (es: "2026-07-15T16:00") ai loro dati meteo
        database_meteo_orario = {}
        for idx, t_str in enumerate(times_str):
            database_meteo_orario[t_str] = {
                "temp": temps[idx],
                "code": codes[idx],
                "wind": winds[idx]
            }
            
        previsioni_lungo_corsa = []
        
        # Campioniamo i dati lungo la corsa (max 6 settori)
        km_totali = len(mappa_orari)
        step_campionamento = max(1, km_totali // 6)
        
        for km in range(1, km_totali + 1, step_campionamento):
            dati_km = mappa_orari[km]
            
            # Orario teorico in cui il runner transiterà in quel Km
            tempo_passaggio = data_partenza + timedelta(seconds=dati_km["secondi_da_partenza"])
            
            # Arrotondiamo all'ora più vicina per fare la ricerca nel dizionario meteo dell'API
            minuti = tempo_passaggio.minute
            if minuti >= 30:
                tempo_passaggio_arrotondato = tempo_passaggio + timedelta(hours=1)
            else:
                tempo_passaggio_arrotondato = tempo_passaggio
                
            chiave_ricerca_ora = tempo_passaggio_arrotondato.strftime("%Y-%m-%dT%H:00")
            
            # Se l'orario di passaggio ricade nel nostro database meteo
            if chiave_ricerca_ora in database_meteo_orario:
                dati_meteo = database_meteo_orario[chiave_ricerca_ora]
                temp_modello = dati_meteo["temp"]
                codice_wmo = dati_meteo["code"]
                vento = dati_meteo["wind"]
                
                # Correzione termica dinamica (gradiente verticale di 0.65°C ogni 100m)
                differenza_quota = dati_km["ele"] - elevation_modello
                temperatura_corretta = temp_modello - (differenza_quota / 100.0 * 0.65)
                
                previsioni_lungo_corsa.append({
                    "Settore Percorso": f"Km {km} (Quota {dati_km['ele']:.0f}m s.l.m.)",
                    "Orario di Passaggio": tempo_passaggio.strftime("%d/%m %H:%M"),
                    "Meteo Previsto": interpreta_wmo_code(codice_wmo),
                    "Temp. Corretta in Quota": f"{temperatura_corretta:.1f} °C",
                    "Vento al Suolo": f"{vento:.1f} km/h",
                    "Temp. Base Modello (rif.)": f"{temp_modello:.1f} °C"
                })
                
        return previsioni_lungo_corsa
    except Exception as e:
        st.sidebar.error(f"Errore API Meteo: {e}")
        return []
        
# --- CODICE EMBED MAPPA SATELLITARE 3D ---

def genera_mappa_3d_html(geojson_traccia, key_points, centro_lat, centro_lon, punti_altimetria):
    geojson_str = json.dumps(geojson_traccia)
    kp_json = json.dumps(key_points)
    punti_altimetria_json = json.dumps(punti_altimetria)
    
    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8" />
        <title>MapLibre 3D Satellite Terrain with Chart Sync</title>
        <meta name="viewport" content="initial-scale=1,maximum-scale=1,user-scalable=no" />
        <script src="https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.js"></script>
        <link href="https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.css" rel="stylesheet" />
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            html, body {{ margin: 0; padding: 0; width: 100%; height: 100%; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: #0f172a; overflow: hidden; }}
            #container {{ display: flex; flex-direction: column; width: 100%; height: 100%; }}
            #map {{ flex: 1; width: 100%; min-height: 300px; }}
            #chart-container {{ height: 200px; background: #0f172a; padding: 10px 20px; border-top: 1px solid rgba(255,255,255,0.1); box-sizing: border-box; }}
            
            .map-overlay {{
                position: absolute;
                bottom: 220px;
                left: 20px;
                background: rgba(15, 23, 42, 0.95);
                color: #fff;
                padding: 12px;
                font-size: 11px;
                border-radius: 8px;
                pointer-events: none;
                z-index: 999;
                border: 1px solid rgba(255,255,255,0.1);
            }}
            
            .km-selector-container {{
                position: absolute;
                top: 15px;
                left: 15px;
                background: rgba(15, 23, 42, 0.95);
                padding: 10px;
                border-radius: 8px;
                z-index: 1000;
                border: 1px solid rgba(255,255,255,0.1);
                max-width: 90%;
            }}
            .km-selector-title {{
                color: #94a3b8;
                font-size: 10px;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                margin-bottom: 6px;
                font-weight: bold;
            }}
            .km-btn-group {{
                display: flex;
                gap: 6px;
                overflow-x: auto;
                padding-bottom: 2px;
            }}
            .km-btn {{
                background: #334155;
                color: #f8fafc;
                border: none;
                padding: 6px 10px;
                border-radius: 4px;
                cursor: pointer;
                font-size: 11px;
                font-weight: 500;
                white-space: nowrap;
                transition: all 0.2s ease;
            }}
            .km-btn:hover {{
                background: #28C864;
                color: #0f172a;
            }}
            .reset-btn {{
                background: #ef4444;
            }}
            .reset-btn:hover {{
                background: #f87171;
                color: #fff;
            }}
            
            .mapboxgl-popup-content, .maplibregl-popup-content {{
                background: #0f172a !important;
                color: #f8fafc !important;
                border: 1px solid rgba(255,255,255,0.2);
                border-radius: 12px !important;
                padding: 12px 15px !important;
                box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.5) !important;
            }}
            .mapboxgl-popup-anchor-top .mapboxgl-popup-tip, .maplibregl-popup-anchor-top .maplibregl-popup-tip {{
                border-bottom-color: #0f172a !important;
            }}
        </style>
    </head>
    <body>
        <div id="container">
            <div id="map"></div>
            <div id="chart-container">
                <canvas id="elevationChart"></canvas>
            </div>
        </div>

        <div class="km-selector-container">
            <div class="km-selector-title">👁️ Esplora Visuale Soggettiva (First-Person)</div>
            <div class="km-btn-group" id="btn-group">
                <button class="km-btn reset-btn" id="btn-reset">Vista Globale</button>
            </div>
        </div>

        <div class="map-overlay">
            <strong>Analisi Terreno 3D:</strong><br>
            🟢 Pendenza Regolare<br>
            🟡 Pendenza Intermedia<br>
            🔴 Pendenza Tecnica<br>
            ➤ Freccia: Direzione del Percorso<br>
            💡 <em>Usa il grafico in basso per scorrere il percorso in tempo reale!</em>
        </div>

        <script>
            const map = new maplibregl.Map({{
                container: 'map',
                zoom: 13,
                center: [{centro_lon}, {centro_lat}],
                pitch: 60,
                bearing: -10,
                style: {{
                    version: 8,
                    sources: {{
                        'satellite-tiles': {{
                            type: 'raster',
                            tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}'],
                            tileSize: 256,
                            maxzoom: 19
                        }},
                        'terrainSource': {{
                            type: 'raster-dem',
                            tiles: ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{{z}}/{{x}}/{{y}}.png'],
                            encoding: 'terrarium',
                            tileSize: 256,
                            maxzoom: 15
                        }}
                    }},
                    layers: [
                        {{
                            id: 'satellite-layer',
                            type: 'raster',
                            source: 'satellite-tiles'
                        }}
                    ],
                    terrain: {{
                        source: 'terrainSource',
                        exaggeration: 1.5
                    }}
                }}
            }});

            map.addControl(new maplibregl.NavigationControl());

            const geojsonTraccia = {geojson_str};
            const keyPoints = {kp_json};
            const datiAltimetria = {punti_altimetria_json};
            
            let cursorMarker = null;

            function creaImmagineFreccia() {{
                const size = 24;
                const canvas = document.createElement('canvas');
                canvas.width = size;
                canvas.height = size;
                const ctx = canvas.getContext('2d');

                ctx.fillStyle = '#ffffff';
                ctx.strokeStyle = '#0f172a';
                ctx.lineWidth = 3;

                ctx.beginPath();
                ctx.moveTo(4, 4);
                ctx.lineTo(20, 12);
                ctx.lineTo(4, 20);
                ctx.lineTo(8, 12);
                ctx.closePath();

                ctx.stroke();
                ctx.fill();

                return ctx.getImageData(0, 0, size, size);
            }}

            map.on('load', () => {{
                map.addImage('arrow-icon', creaImmagineFreccia());

                map.addSource('gpx-route', {{
                    'type': 'geojson',
                    'data': geojsonTraccia,
                    'lineMetrics': true
                }});

                map.addLayer({{
                    'id': 'gpx-route-layer',
                    'type': 'line',
                    'source': 'gpx-route',
                    'layout': {{
                        'line-join': 'round',
                        'line-cap': 'round'
                    }},
                    'paint': {{
                        'line-color': ['get', 'color'],
                        'line-width': 5
                    }}
                }});

                map.addLayer({{
                    'id': 'gpx-route-arrows',
                    'type': 'symbol',
                    'source': 'gpx-route',
                    'layout': {{
                        'symbol-placement': 'line',
                        'symbol-spacing': 70,
                        'icon-image': 'arrow-icon',
                        'icon-size': 0.6,
                        'icon-rotate': 0,
                        'icon-rotation-alignment': 'map',
                        'icon-pitch-alignment': 'map',
                        'icon-keep-upright': false,
                        'icon-allow-overlap': true,
                        'icon-ignore-placement': true
                    }}
                }});

                const ctxChart = document.getElementById('elevationChart').getContext('2d');
                const labels = datiAltimetria.map(p => p.distanza_km.toFixed(2));
                const quote = datiAltimetria.map(p => p.ele);

                const chart = new Chart(ctxChart, {{
                    type: 'line',
                    data: {{
                        labels: labels,
                        datasets: [{{
                            label: 'Quota (m s.l.m.)',
                            data: quote,
                            borderColor: '#28C864',
                            borderWidth: 2,
                            fill: true,
                            backgroundColor: 'rgba(40, 200, 100, 0.1)',
                            pointRadius: 0,
                            pointHoverRadius: 6,
                            pointHoverBackgroundColor: '#38bdf8',
                            tension: 0.1
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {{
                            legend: {{ display: false }},
                            tooltip: {{
                                enabled: true,
                                mode: 'index',
                                intersect: false,
                                callbacks: {{
                                    title: (context) => 'Distanza: ' + context[0].label + ' km',
                                    label: (context) => 'Quota: ' + context.parsed.y + ' m'
                                }}
                            }}
                        }},
                        scales: {{
                            x: {{
                                grid: {{ color: 'rgba(255,255,255,0.05)' }},
                                ticks: {{ color: '#94a3b8', maxTicksLimit: 10 }}
                            }},
                            y: {{
                                grid: {{ color: 'rgba(255,255,255,0.05)' }},
                                ticks: {{ color: '#94a3b8' }}
                            }}
                        }},
                        onHover: (event, chartElements) => {{
                            if (chartElements && chartElements.length > 0) {{
                                const index = chartElements[0].index;
                                const puntoCorrente = datiAltimetria[index];
                                
                                if (puntoCorrente) {{
                                    if (!cursorMarker) {{
                                        const el = document.createElement('div');
                                        el.style.width = '14px';
                                        el.style.height = '14px';
                                        el.style.backgroundColor = '#38bdf8';
                                        el.style.border = '2px solid #ffffff';
                                        el.style.borderRadius = '50%';
                                        el.style.boxShadow = '0 0 12px #38bdf8';
                                        
                                        cursorMarker = new maplibregl.Marker(el)
                                            .setLngLat([puntoCorrente.lon, puntoCorrente.lat])
                                            .addTo(map);
                                    }} else {{
                                        cursorMarker.setLngLat([puntoCorrente.lon, puntoCorrente.lat]);
                                    }}
                                }}
                            }}
                        }}
                    }}
                }});

                window.addEventListener('message', (event) => {{
                    try {{
                        const data = JSON.parse(event.data);
                        if (data.action === 'flyToPoint' && data.lat && data.lon) {{
                            map.flyTo({{
                                center: [data.lon, data.lat],
                                zoom: 16.5,
                                pitch: 75,
                                essential: true,
                                duration: 2500
                            }});
                        }}
                    }} catch(err) {{}}
                }});

                map.on('click', 'gpx-route-layer', (e) => {{
                    const coordinates = e.lngLat;
                    const properties = e.features[0].properties;
                    const pendenza = properties.pendenza;
                    const quota = properties.quota;
                    
                    map.flyTo({{
                        center: [coordinates.lng, coordinates.lat],
                        zoom: 16.8,
                        pitch: 78,
                        essential: true,
                        duration: 2000
                    }});
                    
                    const colorPendenza = Math.abs(pendenza) >= 30 ? '#ef4444' : '#28C864';
                    
                    const htmlPopup = '<div style="font-family: sans-serif; font-size:12px; line-height: 1.5; min-width: 160px;">' +
                        '<strong style="font-size:13px; color:#28C864; display:block; margin-bottom:6px;">Telemetria Punto</strong>' +
                        '🏔️ <strong>Quota:</strong> ' + quota + ' m s.l.m.<br>' +
                        '📈 <strong>Pendenza:</strong> <span style="color: ' + colorPendenza + '; font-weight:bold;">' + pendenza + '%</span><br>' +
                        '<hr style="border: 0; border-top: 1px solid rgba(255,255,255,0.1); margin: 6px 0;">' +
                        '<span style="font-size:9px; color:#94a3b8; display:block; text-align:center;">Trascina con il tasto destro per ruotare la visuale!</span>' +
                        '</div>';

                    new maplibregl.Popup()
                        .setLngLat(coordinates)
                        .setHTML(htmlPopup)
                        .addTo(map);
                }});

                map.on('mouseenter', 'gpx-route-layer', () => {{
                    map.getCanvas().style.cursor = 'pointer';
                }});
                map.on('mouseleave', 'gpx-route-layer', () => {{
                    map.getCanvas().style.cursor = '';
                }});

                const btnGroup = document.getElementById('btn-group');
                keyPoints.forEach((kp) => {{
                    const btn = document.createElement('button');
                    btn.className = 'km-btn';
                    btn.innerText = 'Km ' + kp.dist_km.toFixed(1);
                    btn.onclick = () => {{
                        map.flyTo({{
                            center: [kp.lon, kp.lat],
                            zoom: 16.5,
                            pitch: 78,
                            bearing: kp.bearing,
                            essential: true,
                            duration: 2500
                        }});
                    }};
                    btnGroup.appendChild(btn);
                }});

                document.getElementById('btn-reset').onclick = () => {{
                    map.flyTo({{
                        center: [{centro_lon}, {centro_lat}],
                        zoom: 13,
                        pitch: 60,
                        bearing: -10,
                        duration: 2000
                    }});
                }};
            }});
        </script>
    </body>
    </html>
    """
    return html_code

# --- INTERFACCIA STREAMLIT ---

with st.sidebar:
    st.header("Impostazioni Alpine")
    uploaded_file = st.file_uploader("Carica file GPX", type=["gpx"])
    soglia = st.slider("Pendenza Tecnica (%)", 10, 60, 30, 5)
    
    st.markdown("---")
    st.subheader("Visualizzazione")
    altezza_mappa = st.slider("Altezza mappa (pixel)", 300, 1200, 600, 50)
    
    st.markdown("---")
    st.subheader("Pacer Naismith-Minetti")
    ore_target = st.number_input(
        "Tempo Obiettivo (Ore)", 
        min_value=1.0, 
        max_value=100.0, 
        value=13.0, 
        step=0.5,
        help="Inserisci il tempo target finale. Il sistema distribuirà il passo per km tenendo conto del dislivello reale."
    )
    
    # --- CONFIGURAZIONE DATA E ORA PARTENZA METEO ---
    st.markdown("---")
    st.subheader("⏱️ Configurazione Partenza")
    data_giorno = st.date_input("Giorno Gara / Partenza", datetime.now().date())
    ora_partenza = st.time_input("Ora di Partenza", datetime.now().time())
    
    data_partenza_completa = datetime.combine(data_giorno, ora_partenza)
    
    st.markdown("---")
    st.subheader("Performance")
    semplifica = st.selectbox(
        "Semplificazione traccia",
        options=[1, 2, 3, 5],
        index=0,
        format_func=lambda x: "Disattiva (Massimo dettaglio)" if x == 1 else f"Leggera (Prendi 1 punto ogni {x})"
    )

if uploaded_file:
    punti = parse_gpx(uploaded_file)
    
    if len(punti) > 3000 and semplifica == 1:
        semplifica = 3
        st.sidebar.warning(f"La traccia ha {len(punti)} punti. Ho attivato un'auto-semplificazione (1 ogni 3) per fluidità.")

    if len(punti) < 3:
        st.error("Carica un file GPX valido con almeno 3 punti traccia.")
    else:
        # Analisi dei dati
        geojson_traccia, dist_tot, d_pos, dist_tech, df_punti, tratti_critici = analizza_percorso(punti, soglia, semplifica)
        
        punti_chiave = np.linspace(0, len(df_punti)-2, num=8, dtype=int)
        key_points = []
        for p_idx in punti_chiave:
            pt = df_punti.iloc[p_idx]
            pt_next = df_punti.iloc[p_idx+1]
            bearing_sentiero = calcola_bearing(pt['lat'], pt['lon'], pt_next['lat'], pt_next['lon'])
            key_points.append({
                "dist_km": float(pt['distanza_km']),
                "lat": float(pt['lat']),
                "lon": float(pt['lon']),
                "bearing": float(bearing_sentiero)
            })

        # Metriche Principali
        col1, col2, col3 = st.columns(3)
        col1.metric("Lunghezza Percorso", f"{dist_tot / 1000.0:.2f} km")
        col2.metric("Dislivello Positivo", f"{d_pos:.0f} m+")
        col3.metric("Passaggi Tecnici (Sopra Soglia)", f"{dist_tech / 1000.0:.2f} km")
        
        # --- CALCOLO TABELLA PACER & ORARI PASSAGGIO ---
        df_pacer, mappa_orari = calcola_pacer_tabella(df_punti, ore_target)
        
        # --- SEZIONE METEO DINAMICO LUNGO IL PERCORSO (NUOVA INSERZIONE) ---
        st.markdown("---")
        st.subheader("🌤️ Bollettino Meteo in Corsa (Gradiente Termico Verticale)")
        st.caption("Il sistema calcola l'ora esatta di passaggio in ogni settore della gara in base al tuo pacer ed interroga Open-Meteo correggendo la temperatura in base all'altitudine effettiva in quel punto!")
        
        centro_lat = df_punti['lat'].mean()
        centro_lon = df_punti['lon'].mean()
        
        previsioni_strada = scarica_meteo_percorso(centro_lat, centro_lon, data_partenza_completa, mappa_orari, ore_target)
        
        if previsioni_strada:
            df_meteo = pd.DataFrame(previsioni_strada)
            st.dataframe(df_meteo, use_container_width=True, hide_index=True)
        else:
            st.warning("⚠️ Impossibile caricare le previsioni meteo per questa coordinata o l'orario di arrivo supera la finestra di previsione a 3 giorni.")
        
        # --- TABELLA FASCE ALTIMETRICHE ---
        st.markdown("---")
        st.subheader("📊 Ripartizione del Percorso per Quote Altimetriche")
        st.caption("Fasce altimetriche toccate dal tracciato con distanza esatta e percentuale sul totale del percorso.")
        
        df_fasce = calcola_fasce_altimetriche(df_punti)
        if not df_fasce.empty:
            col_tab, col_graf = st.columns([1, 1])
            with col_tab:
                st.dataframe(df_fasce, use_container_width=True, hide_index=True)
            with col_graf:
                st.bar_chart(df_fasce, x="Fascia Altimetrica", y="Percentuale (%)", color="#28C864")
        else:
            st.info("Nessun dato altimetrico rilevato nel file GPX.")
            
        st.markdown("---")
        
        # Mappa 3D Reale con Altimetria Integrata
        st.subheader("🏔️ Mappa Alpinistica 3D Satellitare & Profilo Sincronizzato")
        st.caption("💡 Trascina con il tasto destro per inclinare la montagna. Passa il mouse sul profilo altimetrico sotto la mappa per muovere il cursore azzurro sulla traccia 3D!")
        
        lista_punti_json = df_punti[['distanza_km', 'ele', 'lat', 'lon']].to_dict(orient='records')
        
        mappa_html = genera_mappa_3d_html(geojson_traccia, key_points, centro_lat, centro_lon, lista_punti_json)
        components.html(mappa_html, height=altezza_mappa + 250)
        
        # --- TABELLA INTERATTIVA DEI TRATTI CRITICI ---
        st.markdown("---")
        st.subheader("⚠️ Analisi dei Tratti Critici (Salite e Discese Verticali)")
        st.caption("La seguente tabella raggruppa le porzioni consecutive di sentiero che superano la pendenza tecnica selezionata. Clicca su un pulsante 'Tratto' per posizionare la telecamera in soggettiva all'inizio di quel tratto!")
        
        if tratti_critici:
            df_tratti = pd.DataFrame(tratti_critici)
            
            cols_grid = st.columns(min(len(tratti_critici), 6))
            for idx, tratto in enumerate(tratti_critici[:12]):
                with cols_grid[idx % len(cols_grid)]:
                    colore_tipo = "🔴" if tratto["Tipo"] == "Salita" else "🔵"
                    pulsante_testo = f"{colore_tipo} Tratto {tratto['ID']} (Km {tratto['Inizio (Km)']})"
                    if st.button(pulsante_testo, key=f"btn_tratto_{tratto['ID']}"):
                        js_fly = f"""
                            <script>
                                window.parent.postMessage(JSON.stringify({{
                                    action: "flyToPoint",
                                    lat: {tratto['lat']},
                                    lon: {tratto['lon']}
                                }}), "*");
                            </script>
                        """
                        components.html(js_fly, height=0)
            
            st.dataframe(
                df_tratti[["ID", "Tipo", "Inizio (Km)", "Lunghezza (m)", "Pendenza Media (%)", "Dislivello (m)"]],
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("👍 Nessun tratto critico rilevato sopra la pendenza tecnica impostata.")

        # --- SEZIONE PACER VIRTUALE NAISMITH-MINETTI ---
        st.markdown("---")
        st.subheader("🏃‍♂️ Tabella di Marcia e Pacer Naismith-Minetti")
        st.write(f"Modello di passo personalizzato calibrato sulla salita e sulla discesa per completare il percorso in **{ore_target} ore**.")
        
        if not df_pacer.empty:
            st.dataframe(df_pacer, use_container_width=True, hide_index=True)
        else:
            st.warning("Impossibile generare la tabella del pacer. Verifica i dati GPX.")

else:
    st.info("👋 Carica il tuo file GPX per attivare il terreno 3D montano e la telemetria alpinistica.")
