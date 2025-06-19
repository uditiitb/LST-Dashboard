import ee
import geopandas as gpd
import zipfile
import os
import json
from datetime import datetime

# === CONFIG ===
# CITY = "MUMBAI"
# SHAPEFILE_ZIP = f"shapefiles/{CITY}.zip"
# DATA_DIR = f"static/data_json/{CITY}"

# os.makedirs(DATA_DIR, exist_ok=True)
# month_ranges = [
#     ("2023-01-01", "2023-01-31"),
#     ("2023-04-01", "2023-04-30"),
#     ("2023-06-01", "2023-06-30"),
# ]

# # === AUTH ===
# service_account = "lst-project@daring-night-422219-d4.iam.gserviceaccount.com"
# credentials = ee.ServiceAccountCredentials(service_account, 'daring-night-422219-d4-1a31eb1a4295.json')
# ee.Initialize(credentials)

# # === UNZIP SHAPEFILE ===
# unzip_dir = f"shp_temp/{CITY}"
# os.makedirs(unzip_dir, exist_ok=True)
# with zipfile.ZipFile(SHAPEFILE_ZIP, 'r') as zip_ref:
#     zip_ref.extractall(unzip_dir)

# # === LOAD SHAPEFILE ===
# shp_file = [f for f in os.listdir(unzip_dir) if f.endswith(".shp")][0]
# gdf = gpd.read_file(os.path.join(unzip_dir, shp_file))
# geometry = ee.Geometry(gdf.geometry.union_all().__geo_interface__)

# # === LST FUNCTION ===
# def compute_lst(image):
#     return image.select('ST_B10').multiply(0.00341802).add(149.0).subtract(273.15).rename('LST')

# month_labels = []

# for start, end in month_ranges:
#     month_str = datetime.strptime(start, "%Y-%m-%d").strftime("%B-%Y")
#     month_dir = os.path.join(DATA_DIR, month_str)
    
#     # Check if all required files already exist
#     if os.path.exists(os.path.join(month_dir, "ward_geojson.json")) and \
#        os.path.exists(os.path.join(month_dir, "top10_lst_data.json")) and \
#        os.path.exists(os.path.join(month_dir, "min_max_lst.json")):
#         print(f"✅ Skipping {month_str} (already exists)")
#         month_labels.append(month_str)
#         continue

#     print(f"⏳ Processing {month_str}...")

#     collection = ee.ImageCollection("LANDSAT/LC08/C02/T1_L2") \
#         .filterBounds(geometry) \
#         .filterDate(start, end) \
#         .map(compute_lst)

#     lst_image = collection.median().clip(geometry)

#     avg_lst_list = []
#     for _, row in gdf.iterrows():
#         print(row)
#         poly_geojson = row.geometry.__geo_interface__
#         if poly_geojson['type'] == 'Polygon':
#             ee_poly = ee.Geometry.Polygon(poly_geojson['coordinates'])
#         elif poly_geojson['type'] == 'MultiPolygon':
#             ee_poly = ee.Geometry.MultiPolygon(poly_geojson['coordinates'])
#         else:
#             avg_lst_list.append(None)
#             continue
#         try:
#             mean_dict = lst_image.reduceRegion(
#                 reducer=ee.Reducer.mean(),
#                 geometry=ee_poly,
#                 scale=1000,
#                 maxPixels=1e12
#             ).getInfo()
#             avg_lst = mean_dict.get('LST', None)
#         except Exception as e:
#             avg_lst = None
#         avg_lst_list.append(avg_lst)

#     temp_gdf = gdf.copy()
#     temp_gdf['avg_LST'] = avg_lst_list

#     valid_lst = temp_gdf['avg_LST'].dropna()
#     quantiles = valid_lst.quantile([0.2, 0.4, 0.6, 0.8]).tolist()

#     def assign_color_class(lst):
#         if lst is None:
#             return 0
#         elif lst <= quantiles[0]:
#             return 1
#         elif lst <= quantiles[1]:
#             return 2
#         elif lst <= quantiles[2]:
#             return 3
#         elif lst <= quantiles[3]:
#             return 4
#         else:
#             return 5

#     temp_gdf['color_class'] = temp_gdf['avg_LST'].apply(assign_color_class)
#     os.makedirs(month_dir, exist_ok=True)

#     # Save ward GeoJSON
#     with open(os.path.join(month_dir, "ward_geojson.json"), "w") as f:
#         json.dump(json.loads(temp_gdf.to_json()), f)

#     # Save top 10 LST wards
#     sorted_gdf = temp_gdf.sort_values(by='avg_LST', ascending=False).head(10)
#     top10_data = [
#         {"ward": str(row.get('WARD_NO', row.get('Name', i))), "lst": row['avg_LST']}
#         for i, row in sorted_gdf.iterrows()
#     ]
#     with open(os.path.join(month_dir, "top10_lst_data.json"), "w") as f:
#         json.dump(top10_data, f)

#     # Save min/max LST values
#     lst_vals = [val for val in temp_gdf['avg_LST'] if val is not None]
#     with open(os.path.join(month_dir, "min_max_lst.json"), "w") as f:
#         json.dump({'min': min(lst_vals), 'max': max(lst_vals)}, f)

#     month_labels.append(month_str)

# # Save master month labels
# with open(os.path.join(DATA_DIR, "month_labels.json"), "w") as f:
#     json.dump(month_labels, f)

# print("✅ Done. Data organized per month in folders inside 'data_json/'.")

# # === YEARLY AVERAGES ===
# output_dir = f"static/data_json/{CITY}"
# os.makedirs(output_dir, exist_ok=True)  # Ensure directory exists

# yearly_lst = {}

# for year in range(2013, 2025):  # Last 12 years
#     file_path = os.path.join(output_dir, f"{year}.json")
    
#     # Skip if file already exists
#     if os.path.exists(file_path):
#         print(f"⏭️ Skipping {year}, file already exists.")
#         continue

#     print(f"🔄 Processing {year}")
#     start = f"{year}-01-01"
#     end = f"{year}-12-31"

#     collection = ee.ImageCollection("LANDSAT/LC08/C02/T1_L2") \
#         .filterBounds(geometry) \
#         .filterDate(start, end) \
#         .map(compute_lst)

#     lst_image = collection.median().clip(geometry)

#     stats = lst_image.reduceRegion(
#         reducer=ee.Reducer.mean(),
#         geometry=geometry,
#         scale=1000,
#         maxPixels=1e13
#     ).getInfo()

#     avg = stats.get("LST")
#     print(f"{year}: {avg}")
#     yearly_lst[year] = avg

#     # Save to individual file
#     with open(file_path, "w") as f:
#         json.dump({year: avg}, f, indent=2)
#     print(f"✅ Saved {year} LST to {file_path}")


# OUTPUT_DIR = f"static/data_json/{CITY}/lst_layer/2023"
# os.makedirs(OUTPUT_DIR, exist_ok=True)

# # === Visualization for LST ===
# lst_vis = {
#     'min': 15,
#     'max': 45,
#     'palette': ['blue', 'cyan', 'green', 'yellow', 'red']
# }


# # === PROCESS EACH MONTH ===

# for start, end in month_ranges:
#     month_name = start[5:7]
#     output_path = os.path.join(OUTPUT_DIR, f"{month_name}.json")

#     if os.path.exists(output_path):
#         print(f"⏭️ Skipping {month_name} — file already exists.")
#         continue

#     print(f"🔄 Processing {start} to {end}")

#     # Filter and calculate median LST image
#     collection = ee.ImageCollection("LANDSAT/LC08/C02/T1_L2") \
#         .filterBounds(geometry) \
#         .filterDate(start, end) \
#         .map(compute_lst)

#     median_image = collection.median().clip(geometry)

#     # Calculate city-wide average
#     stats = median_image.reduceRegion(
#         reducer=ee.Reducer.mean(),
#         geometry=geometry,
#         scale=1000,
#         maxPixels=1e13
#     )
#     avg_lst = ee.Number(stats.get('LST'))
#     threshold = avg_lst.multiply(1.2)

#     # Mask out values below threshold
#     masked_image = median_image.updateMask(median_image.gt(threshold)).rename('LST')

#     # Get tile URL from Earth Engine
#     mapid = masked_image.getMapId(lst_vis)
#     tile_url = mapid['tile_fetcher'].url_format

#     # Write output to JSON
#     with open(output_path, "w") as f:
#         json.dump({
#             "start": start,
#             "end": end,
#             "avg_value": avg_lst.getInfo(),
#             "threshold_value": threshold.getInfo(),
#             "tile_url": tile_url
#         }, f, indent=2)

#     print(f"✅ Saved {month_name}.json with avg LST and masked tile.")

from flask import Flask, render_template

app = Flask(__name__, template_folder="templates")

@app.route("/")
def home():
    return render_template("home.html")

@app.route('/favicon.ico')
def favicon():
    return '', 204  # No Content

@app.route("/city/<city>")
def city_dashboard(city):

    # === CONFIG ===
    CITY=city.capitalize()
    SHAPEFILE_ZIP = f"shapefiles/{CITY}.zip"
    DATA_DIR = f"static/data_json/{CITY}"

    os.makedirs(DATA_DIR, exist_ok=True)
    month_ranges = [
        ("2023-01-01", "2023-01-31"),
        ("2023-04-01", "2023-04-30"),
    ]

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
    def compute_lst(image):
        return image.select('ST_B10').multiply(0.00341802).add(149.0).subtract(273.15).rename('LST')

    month_labels = []

    for start, end in month_ranges:
        month_str = datetime.strptime(start, "%Y-%m-%d").strftime("%B-%Y")
        print(month_str)
        month_dir = os.path.join(DATA_DIR, month_str)
        print(month_dir)
        
        # Check if all required files already exist
        if os.path.exists(os.path.join(month_dir, "ward_geojson.json")) and \
        os.path.exists(os.path.join(month_dir, "top10_lst_data.json")) and \
        os.path.exists(os.path.join(month_dir, "min_max_lst.json")):
            month_labels.append(month_str)
            continue

        print(f"⏳ Processing {month_str}...")

        collection = ee.ImageCollection("LANDSAT/LC08/C02/T1_L2") \
            .filterBounds(geometry) \
            .filterDate(start, end) \
            .map(compute_lst)

        lst_image = collection.median().clip(geometry)

        avg_lst_list = []
        for _, row in gdf.iterrows():
            print(row)
            poly_geojson = row.geometry.__geo_interface__
            if poly_geojson['type'] == 'Polygon':
                ee_poly = ee.Geometry.Polygon(poly_geojson['coordinates'])
            elif poly_geojson['type'] == 'MultiPolygon':
                ee_poly = ee.Geometry.MultiPolygon(poly_geojson['coordinates'])
            else:
                avg_lst_list.append(None)
                continue
            try:
                mean_dict = lst_image.reduceRegion(
                    reducer=ee.Reducer.mean(),
                    geometry=ee_poly,
                    scale=1000,
                    maxPixels=1e12
                ).getInfo()
                avg_lst = mean_dict.get('LST', None)
            except Exception as e:
                avg_lst = None
            avg_lst_list.append(avg_lst)

        temp_gdf = gdf.copy()
        temp_gdf['avg_LST'] = avg_lst_list

        valid_lst = temp_gdf['avg_LST'].dropna()
        quantiles = valid_lst.quantile([0.2, 0.4, 0.6, 0.8]).tolist()

        def assign_color_class(lst):
            if lst is None:
                return 0
            elif lst <= quantiles[0]:
                return 1
            elif lst <= quantiles[1]:
                return 2
            elif lst <= quantiles[2]:
                return 3
            elif lst <= quantiles[3]:
                return 4
            else:
                return 5

        temp_gdf['color_class'] = temp_gdf['avg_LST'].apply(assign_color_class)
        os.makedirs(month_dir, exist_ok=True)

        # Save ward GeoJSON
        with open(os.path.join(month_dir, "ward_geojson.json"), "w") as f:
            json.dump(json.loads(temp_gdf.to_json()), f)

        # Save top 10 LST wards
        sorted_gdf = temp_gdf.sort_values(by='avg_LST', ascending=False).head(10)
        print("sorted: ", sorted_gdf)
        top10_data = []
        if(CITY=="MUMBAI"):
            top10_data = [
                {"ward": str(row.get('WARD_NO', row.get('Name', i))), "lst": row['avg_LST']}
                for i, row in sorted_gdf.iterrows()
            ]
        if(CITY=="BANGALORE" or CITY=="Bangalore"):
            top10_data = [
                {"ward": row.get('KGISWardNa'), "lst": row['avg_LST']}
                for i, row in sorted_gdf.iterrows()
            ]
            print(top10_data)
        
        with open(os.path.join(month_dir, "top10_lst_data.json"), "w") as f:
            json.dump(top10_data, f)

        # Save min/max LST values
        lst_vals = [val for val in temp_gdf['avg_LST'] if val is not None]
        with open(os.path.join(month_dir, "min_max_lst.json"), "w") as f:
            json.dump({'min': min(lst_vals), 'max': max(lst_vals)}, f)

        month_labels.append(month_str)

    # Save master month labels
    with open(os.path.join(DATA_DIR, "month_labels.json"), "w") as f:
        json.dump(month_labels, f)

    print("✅ Done. Data organized per month in folders inside 'data_json/'.")

    # === YEARLY AVERAGES ===
    output_dir = f"static/data_json/{CITY}"
    os.makedirs(output_dir, exist_ok=True)  # Ensure directory exists

    yearly_lst = {}

    for year in range(2013, 2025):  # Last 12 years
        file_path = os.path.join(output_dir, f"{year}.json")
        
        # Skip if file already exists
        if os.path.exists(file_path):
            print(f"⏭️ Skipping {year}, file already exists.")
            continue

        print(f"🔄 Processing {year}")
        start = f"{year}-01-01"
        end = f"{year}-12-31"

        collection = ee.ImageCollection("LANDSAT/LC08/C02/T1_L2") \
            .filterBounds(geometry) \
            .filterDate(start, end) \
            .map(compute_lst)

        lst_image = collection.median().clip(geometry)

        stats = lst_image.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometry,
            scale=1000,
            maxPixels=1e13
        ).getInfo()

        avg = stats.get("LST")
        print(f"{year}: {avg}")
        yearly_lst[year] = avg

        # Save to individual file
        with open(file_path, "w") as f:
            json.dump({year: avg}, f, indent=2)
        print(f"✅ Saved {year} LST to {file_path}")


    OUTPUT_DIR = f"static/data_json/{CITY}/lst_layer/2023"
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # === Visualization for LST ===
    lst_vis = {
        'min': 15,
        'max': 45,
        'palette': ['blue', 'cyan', 'green', 'yellow', 'red']
    }


    # === PROCESS EACH MONTH ===

    for start, end in month_ranges:
        month_name = start[5:7]
        output_path = os.path.join(OUTPUT_DIR, f"{month_name}.json")

        if os.path.exists(output_path):
            print(f"⏭️ Skipping {month_name} — file already exists.")
            continue

        print(f"🔄 Processing {start} to {end}")

        # Filter and calculate median LST image
        collection = ee.ImageCollection("LANDSAT/LC08/C02/T1_L2") \
            .filterBounds(geometry) \
            .filterDate(start, end) \
            .map(compute_lst)

        median_image = collection.median().clip(geometry)

        # Calculate city-wide average
        stats = median_image.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometry,
            scale=1000,
            maxPixels=1e13
        )
        avg_lst = ee.Number(stats.get('LST'))
        threshold = avg_lst.multiply(1.2)

        # Mask out values below threshold
        masked_image = median_image.updateMask(median_image.gt(threshold)).rename('LST')

        # Get tile URL from Earth Engine
        mapid = masked_image.getMapId(lst_vis)
        tile_url = mapid['tile_fetcher'].url_format

        # Write output to JSON
        with open(output_path, "w") as f:
            json.dump({
                "start": start,
                "end": end,
                "avg_value": avg_lst.getInfo(),
                "threshold_value": threshold.getInfo(),
                "tile_url": tile_url
            }, f, indent=2)

        print(f"✅ Saved {month_name}.json with avg LST and masked tile.")
    return render_template(f"{city}.html", CITY=city.capitalize())

@app.route("/city/<city>/plot1")
def plot1(city):
    return render_template(f"{city}_plot1.html", CITY=city.capitalize())

@app.route("/city/<city>/plot2and3")
def plot2and3(city):
    print(f"here {city}")
    return render_template(f"{city}_plot2and3.html", CITY=city.capitalize())

@app.route("/city/<city>/plot4")
def plot4(city):
    return render_template(f"{city}_plot4.html", CITY=city.capitalize())



if __name__ == "__main__":
    app.run(debug=True)
