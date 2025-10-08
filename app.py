import ee
import geopandas as gpd
import zipfile
import os
import json
from datetime import datetime, timedelta
from datetime import date
from dateutil.relativedelta import relativedelta          # pip install python-dateutil
import calendar
import xarray as xr
import pandas as pd

from flask import Flask, render_template
from apscheduler.schedulers.background import BackgroundScheduler
import requests
import atexit
import concurrent.futures

from geopy.geocoders import Nominatim
from shapely.geometry import Point
from geopy.extra.rate_limiter import RateLimiter




app = Flask(__name__, template_folder="templates")
# List of cities
cities = [
    "MUMBAI", "DELHI", "BANGALORE"
]

# Change this to your actual base URL and port if running externally
BASE_URL = "http://127.0.0.1:5050"

def call_city_plot(city):
    try:
        response = requests.get(f"{BASE_URL}/city/{city}/plot")
        print(f"[{city}] Status: {response.status_code}")
    except Exception as e:
        print(f"[{city}] Error: {e}")

def trigger_parallel_requests():
    print("Triggering parallel requests to /city/<city>/plot...")
    with concurrent.futures.ThreadPoolExecutor() as executor:
        executor.map(call_city_plot, cities)

# Schedule job on 1st of every month at 12:00 AM
scheduler = BackgroundScheduler()
scheduler.add_job(trigger_parallel_requests, 'cron', day=1, hour=0, minute=0)
scheduler.start()

# Graceful shutdown
atexit.register(lambda: scheduler.shutdown())

@app.route("/")
def home():
    return render_template("home.html")

# Ensure scheduler stops with app


@app.route('/favicon.ico')
def favicon():
    return '', 204  # No Content

@app.route("/city/<city>/plot")
def city_dashboard(city):

    # === CONFIG ===
    # CITY=city.capitalize()
    CITY = city.strip().upper()
    SHAPEFILE_ZIP = f"shapefiles/{CITY}.zip"
    DATA_DIR = f"static/data_json/{CITY}"

    os.makedirs(DATA_DIR, exist_ok=True)
    # Get today's date
    today = datetime.today()

    # Get the first day of this month
    first_day_this_month = today.replace(day=1)

    # Get first day of last month and the month before
    first_last_month = first_day_this_month - relativedelta(months=1)
    first_prev_month = first_day_this_month - relativedelta(months=2)

    # Get the last days of those months
    last_last_month = first_day_this_month - relativedelta(days=1)
    last_prev_month = first_last_month - relativedelta(days=1)

    # Format as strings
    month_ranges = [
        (first_last_month.strftime("%Y-%m-%d"), last_last_month.strftime("%Y-%m-%d")),
        (first_prev_month.strftime("%Y-%m-%d"), last_prev_month.strftime("%Y-%m-%d")),
    ]
    # month_ranges = [
    #     ("2025-04-01", "2025-04-30"),
    #     ("2025-05-01", "2025-05-31")
    # ]
    print(month_ranges)

    # === AUTH ===
    service_account = "lst-223@daring-night-422219-d4.iam.gserviceaccount.com"
    credentials = ee.ServiceAccountCredentials(service_account, '/etc/secrets/daring-night-422219-d4-f5041b31a346.json')
    ee.Initialize(credentials)

    # === UNZIP SHAPEFILE ===
    unzip_dir = f"shp_temp/{CITY}"
    os.makedirs(unzip_dir, exist_ok=True)
    with zipfile.ZipFile(SHAPEFILE_ZIP, 'r') as zip_ref:
        zip_ref.extractall(unzip_dir)

    # === LOAD SHAPEFILE ===
    shp_file = [f for f in os.listdir(unzip_dir) if f.endswith(".shp")][0]
    gdf = gpd.read_file(os.path.join(unzip_dir, shp_file))
    geometry = ee.Geometry(gdf.geometry.union_all().__geo_interface__)

    
    def add_lst_and_cloud(img):
        lst = img.select('ST_B10').multiply(0.00341802).add(149.0).subtract(273.15).rename('LST')
        qa = img.select('QA_PIXEL')
        cloud = qa.bitwiseAnd(1 << 3).Or(qa.bitwiseAnd(1 << 4))  # cloud or cloud shadow
        mask = cloud.Not()
        return lst.updateMask(mask).rename('LST').set('system:time_start', img.get('system:time_start'))


    month_labels = []

    for start, end in month_ranges:
        month_str = datetime.strptime(start, "%Y-%m-%d").strftime("%B-%Y")
        month_dir = os.path.join(DATA_DIR, month_str)
        
        if os.path.exists(os.path.join(month_dir, "ward_geojson.json")):
            month_labels.append(month_str)
            continue

        print(f"⏳ Processing {month_str}...")

        # Get cloud-masked LST stack
        stack = (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
                .merge(ee.ImageCollection("LANDSAT/LC09/C02/T1_L2"))
                .filterBounds(geometry)
                .filterDate(start, end)
                .map(add_lst_and_cloud))

        # Create mask of pixels that are ever clear in time range
        has_clear = stack.select('LST').count().gt(0)

        # Compute median of cloud-free pixels only
        lst_image = (stack.select('LST')
                    .median()
                    .clip(geometry)
                    .updateMask(has_clear))

        # Now per-ward LST calculation using only cloud-free pixels
        avg_lst_list = []
        cloud_cover_list = []
        print(len(gdf))
        for _, row in gdf.iterrows():
            print(row)
            poly_geojson = row.geometry.__geo_interface__
            if poly_geojson['type'] == 'Polygon':
                ee_poly = ee.Geometry.Polygon(poly_geojson['coordinates'])
            elif poly_geojson['type'] == 'MultiPolygon':
                ee_poly = ee.Geometry.MultiPolygon(poly_geojson['coordinates'])
            else:
                avg_lst_list.append(None)
                cloud_cover_list.append(1)
                continue

            try:
                # Average LST over ward
                mean_dict = lst_image.reduceRegion(
                    reducer=ee.Reducer.mean(),
                    geometry=ee_poly,
                    scale=1000,
                    maxPixels=1e13,
                    bestEffort=True
                ).getInfo()
                avg_lst = mean_dict.get('LST', None)
            except Exception:
                avg_lst = None

            avg_lst_list.append(avg_lst)

            try:
                # % cloud coverage: if all pixels are masked, cloud cover is 1
                clear_fraction = lst_image.unmask().reduceRegion(
                    reducer=ee.Reducer.count(),
                    geometry=ee_poly,
                    scale=1000,
                    maxPixels=1e13,
                    bestEffort=True
                ).getInfo().get('LST', 0)

                cloud_cover = 1 if clear_fraction == 0 else 0
            except Exception:
                cloud_cover = 1

            cloud_cover_list.append(cloud_cover)

        # Store in temp GeoDataFrame
        temp_gdf = gdf.copy()
        temp_gdf['avg_LST'] = avg_lst_list
        temp_gdf['cloud_cover'] = cloud_cover_list

        # Filter valid LST and cloud-free
        valid_gdf = temp_gdf[(temp_gdf['avg_LST'].notna()) & (temp_gdf['cloud_cover'] == 0)]
        valid_lst = valid_gdf['avg_LST']

        # Create folder
        os.makedirs(month_dir, exist_ok=True)

        # Save GeoJSON (including cloud-covered wards)
        with open(os.path.join(month_dir, "ward_geojson.json"), "w") as f:
            json.dump(json.loads(temp_gdf.to_json()), f)

        # Save top-10 hottest wards (from valid only)
        sorted_gdf = valid_gdf.sort_values(by='avg_LST', ascending=False).head(10)
        top10_data = []

        if CITY.upper() == "MUMBAI":
            top10_data = [{"ward": str(row.get('Name', i)), "lst": row['avg_LST']} for i, row in sorted_gdf.iterrows()]
        elif CITY.upper() == "BANGALORE":
            top10_data = [{"ward": row.get('KGISWardNa'), "lst": row['avg_LST']} for i, row in sorted_gdf.iterrows()]
        else:
            top10_data = [{"ward": row.get('name'), "lst": row['avg_LST']} for i, row in sorted_gdf.iterrows()]

        with open(os.path.join(month_dir, "top10_lst_data.json"), "w") as f:
            json.dump(top10_data, f)

        # Save min/max values
        lst_vals = valid_lst.tolist()
        with open(os.path.join(month_dir, "min_max_lst.json"), "w") as f:
            if lst_vals:
                json.dump({'min': min(lst_vals), 'max': max(lst_vals)}, f)
            else:
                json.dump({'min': None, 'max': None}, f)

        # Add to available months
        month_labels.append(month_str)

    # === YEARLY AVERAGES ===
    output_dir =  os.path.join(DATA_DIR, "yearly_avg_era5_M")
    os.makedirs(output_dir, exist_ok=True)

    start_year = 1980
    end_year = datetime.now().year-1

    for year in range(start_year, end_year + 1):
        output_path = os.path.join(output_dir, f"{year}.json")
        if os.path.exists(output_path):
            print(f"⏭️ Skipping {year}, file exists.")
            continue

        print(f"🔄 Processing meteoblue-style for {year}...")

        start_date = f"{year}-01-01"
        end_date = f"{year + 1}-01-01"

        # Get ERA5 hourly data
        hourly = ee.ImageCollection("ECMWF/ERA5_LAND/HOURLY") \
            .filterBounds(geometry) \
            .filterDate(start_date, end_date) \
            .select(["temperature_2m"])

        # Create daily composites of min and max temperature
        def to_day(img):
            return ee.Date(img.date().format("YYYY-MM-dd"))

        daily_min = hourly.reduceColumns(
            reducer=ee.Reducer.toList(),
            selectors=["system:time_start"]
        )

        daily_temps = hourly.map(lambda img: img.set("date", img.date().format("YYYY-MM-dd")))
        daily_min = daily_temps.reduce(ee.Reducer.min()).rename("Tmin")
        daily_max = daily_temps.reduce(ee.Reducer.max()).rename("Tmax")

        # Combine to get (Tmin + Tmax)/2 per pixel per day
        daily_avg = daily_min.add(daily_max).divide(2)

        # Convert Kelvin to Celsius
        daily_avg_c = daily_avg.subtract(273.15)

        # Get mean over the year and clip to Bangalore
        mean_image = daily_avg_c.clip(geometry)

        stats = mean_image.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometry,
            scale=250,
            maxPixels=1e13
        ).getInfo()

        avg = stats.get("Tmin")  # The name might differ depending on how layers are named

        with open(output_path, "w") as f:
            json.dump({str(year): avg}, f, indent=2)

        print(f"✅ Year {year} Avg Temp (approximated meteoblue style): {avg:.2f}°C" if avg else f"⚠️ No data for {year}")

    OUTPUT_DIR = f"static/data_json/{CITY}/lst_layer/2025"
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # === Visualization for LST ===
    # ------------------------------------------------------------
    # 0️⃣  Per‑scene work: keep both LST and a cloud‑flag band
    # ------------------------------------------------------------
    def add_lst_and_cloud(img):
        qa = img.select('QA_PIXEL')

        # Define QA flags
        dilated_cloud = 1 << 1
        cirrus        = 1 << 2
        cloud         = 1 << 3
        cloud_shadow  = 1 << 4
        snow          = 1 << 5

        clear = (qa.bitwiseAnd(dilated_cloud).eq(0)
                    .And(qa.bitwiseAnd(cirrus).eq(0))
                    .And(qa.bitwiseAnd(cloud).eq(0))
                    .And(qa.bitwiseAnd(cloud_shadow).eq(0))
                    .And(qa.bitwiseAnd(snow).eq(0)))

        # Only keep clear pixels in LST
        lst = (img.select('ST_B10')
                .multiply(0.00341802)
                .add(149)
                .subtract(273.15)
                .updateMask(clear)
                .rename('LST'))

        # Also return cloud mask for later use
        cloud_flag = clear.Not().rename('cloud')
        result = lst.addBands(cloud_flag).rename(['LST', 'cloud'])
        return result.copyProperties(img, img.propertyNames())

    lst_vis = {
        'min': 15,
        'max': 45,
        'palette': ['blue', 'cyan', 'green', 'yellow', 'red']
    }
    # -----------------------------------------------------------
# 1. loop over your date ranges
# -----------------------------------------------------------
    for start, end in month_ranges:
        print(f'🔄 Processing {start} → {end}')

        # stack = (ee.ImageCollection('LANDSAT/LC08/C02/T1_L2')
        #         .filterBounds(geometry)
        #         .filterDate(start, end)
        #         .map(add_lst_and_cloud))
        stack = (ee.ImageCollection('LANDSAT/LC08/C02/T1_L2')
         .merge(ee.ImageCollection('LANDSAT/LC09/C02/T1_L2'))
         .filterBounds(geometry)
         .filterDate(start, end)
         .map(add_lst_and_cloud))
        dates = (stack
             .aggregate_array('system:time_start')
             .map(lambda t: ee.Date(t).format('YYYY-MM-dd'))
             .getInfo())
        print(f'📅 Raw LC08 dates for {start} → {end}: {dates}')

        all_cloudy = stack.select('cloud').reduce(ee.Reducer.min())   
        has_clear  = all_cloudy.eq(0)                                

        median_lst = (stack.select('LST')
                        .median()
                        .clip(geometry)
                        .updateMask(has_clear))                   
        stats   = median_lst.reduceRegion(
            reducer    = ee.Reducer.mean(),
            geometry   = geometry,
            scale      = 1000,
            maxPixels  = 1e13,
            bestEffort = True
        )
        avg_lst = ee.Number(stats.get('LST'))

        # ----------------------------------------
        threshold_val = avg_lst.multiply(0)           
        lst_layer     = median_lst.updateMask(median_lst.gt(threshold_val))

        cloud_vis     = ['00000000', '00000040', '00000080', '000000C0', '000000FF']
        cloud_display = all_cloudy.clip(geometry).selfMask()         # 1 ⇢ draw pixel, 0 ⇢ transparent

        lst_tile_url   = lst_layer   .getMapId(lst_vis)['tile_fetcher'].url_format
        cloud_tile_url = cloud_display.getMapId({
            'min': 0, 'max': 1, 'palette': cloud_vis
        })['tile_fetcher'].url_format


        out = {
            'start'          : start,
            'end'            : end,
            'avg_value'      : avg_lst.getInfo(),
            'threshold_value': threshold_val.getInfo(),
            'tile_url'       : lst_tile_url,
            'cloud_tile_url' : cloud_tile_url
        }
        month_code = start[5:7]  # e.g. "07"
        with open(os.path.join(OUTPUT_DIR, f'{month_code}.json'), 'w') as f:
            json.dump(out, f, indent=2)

        print(f'✅ Saved {month_code}.json (mean ≈ {avg_lst.getInfo():.2f} °C)\n')


    
    MONTH1 = first_last_month.strftime("%B")
    YEAR1 = first_last_month.strftime("%Y")

    MONTH2 = first_prev_month.strftime("%B")
    YEAR2 = first_prev_month.strftime("%Y")
    
    # MONTH1 = "April"
    # MONTH2 = "May"
    # YEAR1 = 2025
    # YEAR2 = 2025

    return render_template("city_plot.html", CITY=city.capitalize(), MONTH1 =MONTH1, YEAR1 = YEAR1, MONTH2 = MONTH2, YEAR2 = YEAR2)


@app.route("/blog")
def blog():
    return render_template("blog.html")

@app.route("/calender")
def calender():
    return render_template("calender_home.html")

@app.route("/calender/<city>/<int:year>/<int:month>")
def calendar_plot(city, year, month):
    # === CONFIG ===
    # CITY=city.capitalize()
    CITY = city.strip().upper()
    SHAPEFILE_ZIP = f"shapefiles/{CITY}.zip"
    DATA_DIR = f"static/data_json/{CITY}"

    os.makedirs(DATA_DIR, exist_ok=True) 
    # Get first and last date of the month
    first_day = datetime(year, month, 1).strftime("%Y-%m-%d")
    last_day = datetime(year, month, calendar.monthrange(year, month)[1]).strftime("%Y-%m-%d")
    
    # Month range
    month_ranges = [(first_day, last_day)]
    print(month_ranges)

    # === AUTH ===
    service_account = "lst-project@daring-night-422219-d4.iam.gserviceaccount.com"
    credentials = ee.ServiceAccountCredentials(service_account, 'daring-night-422219-d4-1a31eb1a4295.json')
    ee.Initialize(credentials)

    # === UNZIP SHAPEFILE ===
    unzip_dir = f"shp_temp/{CITY}"
    os.makedirs(unzip_dir, exist_ok=True)
    with zipfile.ZipFile(SHAPEFILE_ZIP, 'r') as zip_ref:
        zip_ref.extractall(unzip_dir)

    # === LOAD SHAPEFILE ===
    shp_file = [f for f in os.listdir(unzip_dir) if f.endswith(".shp")][0]
    gdf = gpd.read_file(os.path.join(unzip_dir, shp_file))
    geometry = ee.Geometry(gdf.geometry.union_all().__geo_interface__)

    # === LST FUNCTION ===
    def compute_lst1(image):
        qa = image.select('QA_PIXEL')

        # Bit masks
        dilated_cloud = 1 << 1
        cirrus = 1 << 2
        cloud = 1 << 3
        cloud_shadow = 1 << 4
        snow = 1 << 5

        # Create mask
        mask = (qa.bitwiseAnd(dilated_cloud).eq(0)
                .And(qa.bitwiseAnd(cirrus).eq(0))
                .And(qa.bitwiseAnd(cloud).eq(0))
                .And(qa.bitwiseAnd(cloud_shadow).eq(0))
                .And(qa.bitwiseAnd(snow).eq(0)))

        # Apply mask and compute LST in Celsius
        lst = image.updateMask(mask) \
                .select('ST_B10') \
                .multiply(0.00341802) \
                .add(149.0) \
                .subtract(273.15) \
                .rename('LST')

        return lst
    def compute_lst2(image):
        qa = image.select('QA_PIXEL')
        # Cloud mask from bits (refer to Landsat 8 pixel QA bitmask docs)
        cloud_mask = qa.bitwiseAnd(1 << 3).Or(qa.bitwiseAnd(1 << 4))  # cloud + cloud shadow
        # invert mask: 0 = cloud, 1 = clear
        cloud_free = cloud_mask.Not().rename('clear_mask')
        
        lst = image.select('ST_B10').multiply(0.00341802).add(149.0).subtract(273.15).rename('LST')
        
        return lst.addBands(cloud_free)
    def add_lst_and_cloud(img):
        lst = img.select('ST_B10').multiply(0.00341802).add(149.0).subtract(273.15).rename('LST')
        qa = img.select('QA_PIXEL')
        cloud = qa.bitwiseAnd(1 << 3).Or(qa.bitwiseAnd(1 << 4))  # cloud or cloud shadow
        mask = cloud.Not()
        return lst.updateMask(mask).rename('LST').set('system:time_start', img.get('system:time_start'))

    def compute_lst(image):
        return image.select('ST_B10').multiply(0.00341802).add(149.0).subtract(273.15).rename('LST')

    month_labels = []

    
    for start, end in month_ranges:
        month_str = datetime.strptime(start, "%Y-%m-%d").strftime("%B-%Y")
        month_dir = os.path.join(DATA_DIR, month_str)
        
        if os.path.exists(os.path.join(month_dir, "ward_geojson.json")):
            month_labels.append(month_str)
            continue

        print(f"⏳ Processing {month_str}...")

        # Get cloud-masked LST stack
        stack = (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
                .merge(ee.ImageCollection("LANDSAT/LC09/C02/T1_L2"))
                .filterBounds(geometry)
                .filterDate(start, end)
                .map(add_lst_and_cloud))

        # Create mask of pixels that are ever clear in time range
        has_clear = stack.select('LST').count().gt(0)

        # Compute median of cloud-free pixels only
        lst_image = (stack.select('LST')
                    .median()
                    .clip(geometry)
                    .updateMask(has_clear))

        # Now per-ward LST calculation using only cloud-free pixels
        avg_lst_list = []
        cloud_cover_list = []
        print(len(gdf))
        for _, row in gdf.iterrows():
            print(row)
            poly_geojson = row.geometry.__geo_interface__
            if poly_geojson['type'] == 'Polygon':
                ee_poly = ee.Geometry.Polygon(poly_geojson['coordinates'])
            elif poly_geojson['type'] == 'MultiPolygon':
                ee_poly = ee.Geometry.MultiPolygon(poly_geojson['coordinates'])
            else:
                avg_lst_list.append(None)
                cloud_cover_list.append(1)
                continue

            try:
                # Average LST over ward
                mean_dict = lst_image.reduceRegion(
                    reducer=ee.Reducer.mean(),
                    geometry=ee_poly,
                    scale=1000,
                    maxPixels=1e13,
                    bestEffort=True
                ).getInfo()
                avg_lst = mean_dict.get('LST', None)
            except Exception:
                avg_lst = None

            avg_lst_list.append(avg_lst)

            try:
                # % cloud coverage: if all pixels are masked, cloud cover is 1
                clear_fraction = lst_image.unmask().reduceRegion(
                    reducer=ee.Reducer.count(),
                    geometry=ee_poly,
                    scale=1000,
                    maxPixels=1e13,
                    bestEffort=True
                ).getInfo().get('LST', 0)

                cloud_cover = 1 if clear_fraction == 0 else 0
            except Exception:
                cloud_cover = 1

            cloud_cover_list.append(cloud_cover)

        # Store in temp GeoDataFrame
        temp_gdf = gdf.copy()
        temp_gdf['avg_LST'] = avg_lst_list
        temp_gdf['cloud_cover'] = cloud_cover_list

        # Filter valid LST and cloud-free
        valid_gdf = temp_gdf[(temp_gdf['avg_LST'].notna()) & (temp_gdf['cloud_cover'] == 0)]
        valid_lst = valid_gdf['avg_LST']

        # Compute quantiles only on valid wards
        quantiles = valid_lst.quantile([0.2, 0.4, 0.6, 0.8]).tolist() if not valid_lst.empty else [0, 0, 0, 0]

        # Color classification
        def assign_color_class_safe(row):
            if row['cloud_cover'] == 1 or pd.isna(row['avg_LST']):
                return 0
            val = row['avg_LST']
            if val <= quantiles[0]: return 1
            elif val <= quantiles[1]: return 2
            elif val <= quantiles[2]: return 3
            elif val <= quantiles[3]: return 4
            else: return 5

        temp_gdf['color_class'] = temp_gdf.apply(assign_color_class_safe, axis=1)

        # Create folder
        os.makedirs(month_dir, exist_ok=True)

        # Save GeoJSON (including cloud-covered wards)
        with open(os.path.join(month_dir, "ward_geojson.json"), "w") as f:
            json.dump(json.loads(temp_gdf.to_json()), f)

        # Save top-10 hottest wards (from valid only)
        sorted_gdf = valid_gdf.sort_values(by='avg_LST', ascending=False).head(10)
        top10_data = []

        if CITY.upper() == "MUMBAI":
            top10_data = [{"ward": str(row.get('Name', i)), "lst": row['avg_LST']} for i, row in sorted_gdf.iterrows()]
        elif CITY.upper() == "BANGALORE":
            top10_data = [{"ward": row.get('KGISWardNa'), "lst": row['avg_LST']} for i, row in sorted_gdf.iterrows()]
        else:
            top10_data = [{"ward": row.get('name'), "lst": row['avg_LST']} for i, row in sorted_gdf.iterrows()]

        with open(os.path.join(month_dir, "top10_lst_data.json"), "w") as f:
            json.dump(top10_data, f)

        # Save min/max values
        lst_vals = valid_lst.tolist()
        with open(os.path.join(month_dir, "min_max_lst.json"), "w") as f:
            if lst_vals:
                json.dump({'min': min(lst_vals), 'max': max(lst_vals)}, f)
            else:
                json.dump({'min': None, 'max': None}, f)

        # Add to available months
        month_labels.append(month_str)


    # Save master month labels
    with open(os.path.join(DATA_DIR, "month_labels.json"), "w") as f:
        json.dump(month_labels, f)

    print("✅ Done. Data organized per month in folders inside 'data_json/'.")

    


    OUTPUT_DIR = f"static/data_json/{CITY}/lst_layer/2025"
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # === Visualization for LST ===
    # ------------------------------------------------------------
    # 0️⃣  Per‑scene work: keep both LST and a cloud‑flag band
    # ------------------------------------------------------------
    def add_lst_and_cloud(img):
        qa = img.select('QA_PIXEL')

        # Define QA flags
        dilated_cloud = 1 << 1
        cirrus        = 1 << 2
        cloud         = 1 << 3
        cloud_shadow  = 1 << 4
        snow          = 1 << 5

        clear = (qa.bitwiseAnd(dilated_cloud).eq(0)
                    .And(qa.bitwiseAnd(cirrus).eq(0))
                    .And(qa.bitwiseAnd(cloud).eq(0))
                    .And(qa.bitwiseAnd(cloud_shadow).eq(0))
                    .And(qa.bitwiseAnd(snow).eq(0)))

        # Only keep clear pixels in LST
        lst = (img.select('ST_B10')
                .multiply(0.00341802)
                .add(149)
                .subtract(273.15)
                .updateMask(clear)
                .rename('LST'))

        # Also return cloud mask for later use
        cloud_flag = clear.Not().rename('cloud')
        result = lst.addBands(cloud_flag).rename(['LST', 'cloud'])
        return result.copyProperties(img, img.propertyNames())

    lst_vis = {
        'min': 15,
        'max': 45,
        'palette': ['blue', 'cyan', 'green', 'yellow', 'red']
    }
    # ---- palette for grey overlay ----
    CLOUD_VIS = {'min': 0, 'max': 1, 'palette': ['black']}   # dark‑grey

    
    # -----------------------------------------------------------
# 1. loop over your date ranges
# -----------------------------------------------------------
    for start, end in month_ranges:
        print(f'🔄 Processing {start} → {end}')

        # stack = (ee.ImageCollection('LANDSAT/LC08/C02/T1_L2')
        #         .filterBounds(geometry)
        #         .filterDate(start, end)
        #         .map(add_lst_and_cloud))
        stack = (ee.ImageCollection('LANDSAT/LC08/C02/T1_L2')
         .merge(ee.ImageCollection('LANDSAT/LC09/C02/T1_L2'))
         .filterBounds(geometry)
         .filterDate(start, end)
         .map(add_lst_and_cloud))
        dates = (stack
             .aggregate_array('system:time_start')
             .map(lambda t: ee.Date(t).format('YYYY-MM-dd'))
             .getInfo())
        print(f'📅 Raw LC08 dates for {start} → {end}: {dates}')

        all_cloudy = stack.select('cloud').reduce(ee.Reducer.min())   
        has_clear  = all_cloudy.eq(0)                                

        median_lst = (stack.select('LST')
                        .median()
                        .clip(geometry)
                        .updateMask(has_clear))                   
        stats   = median_lst.reduceRegion(
            reducer    = ee.Reducer.mean(),
            geometry   = geometry,
            scale      = 1000,
            maxPixels  = 1e13,
            bestEffort = True
        )
        avg_lst = ee.Number(stats.get('LST'))

        # ----------------------------------------
        threshold_val = avg_lst.multiply(0)           
        lst_layer     = median_lst.updateMask(median_lst.gt(threshold_val))

        cloud_vis     = ['00000000', '00000040', '00000080', '000000C0', '000000FF']
        cloud_display = all_cloudy.clip(geometry).selfMask()         # 1 ⇢ draw pixel, 0 ⇢ transparent

        lst_tile_url   = lst_layer   .getMapId(lst_vis)['tile_fetcher'].url_format
        cloud_tile_url = cloud_display.getMapId({
            'min': 0, 'max': 1, 'palette': cloud_vis
        })['tile_fetcher'].url_format


        out = {
            'start'          : start,
            'end'            : end,
            'avg_value'      : avg_lst.getInfo(),
            'threshold_value': threshold_val.getInfo(),
            'tile_url'       : lst_tile_url,
            'cloud_tile_url' : cloud_tile_url
        }
        month_code = start[5:7]  # e.g. "07"
        with open(os.path.join(OUTPUT_DIR, f'{month_code}.json'), 'w') as f:
            json.dump(out, f, indent=2)

        print(f'✅ Saved {month_code}.json (mean ≈ {avg_lst.getInfo():.2f} °C)\n')


    return render_template("city_plot_calender.html",CITY=city.capitalize(), MONTH = month, YEAR = year)


if __name__ == "__main__":
    app.run(host='0.0.0.0',debug=True)

