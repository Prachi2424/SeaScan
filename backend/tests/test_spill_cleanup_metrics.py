import numpy as np
import pytest
from pyproj import Geod
from rasterio.transform import from_origin
from app.geospatial.metrics import calculate_spill_metrics
from app.geospatial.satellite import _polygonize

def collection(coordinates):
    return {'type':'FeatureCollection','features':[{'type':'Feature','geometry':{'type':'Polygon','coordinates':coordinates},'properties':{}}]}

def test_holes_subtracted_and_boundaries_counted():
    outer=[[70,20],[70.1,20],[70.1,20.1],[70,20.1],[70,20]]
    inner=[[70.02,20.02],[70.08,20.02],[70.08,20.08],[70.02,20.08],[70.02,20.02]]
    geod=Geod(ellps='WGS84')
    oa,op=geod.polygon_area_perimeter(*zip(*outer))
    ia,ip=geod.polygon_area_perimeter(*zip(*inner))
    result=calculate_spill_metrics(collection([outer,inner]))
    assert result['area_km2']==pytest.approx((abs(oa)-abs(ia))/1e6,abs=1e-5)
    assert result['perimeter_km']==pytest.approx((op+ip)/1000,abs=1e-5)

def test_duplicate_polygons_not_double_counted():
    data=collection([[[70,20],[70.2,20],[70.2,20.02],[70,20.02],[70,20]]])
    single=calculate_spill_metrics(data)
    data['features']*=2
    merged=calculate_spill_metrics(data)
    assert merged['area_km2']==single['area_km2']
    assert merged['component_count']==1
    assert merged['orientation_degrees']==pytest.approx(90,abs=1)
    assert merged['centroid']==pytest.approx([70.1,20.01],abs=.001)

def test_dateline_polygon_is_small_not_global():
    result=calculate_spill_metrics(collection([[[179.9,10],[-179.9,10],[-179.9,10.1],[179.9,10.1],[179.9,10]]]))
    assert 200<result['area_km2']<300
    assert abs(result['centroid'][0])>179

def test_cleanup_preserves_large_component_and_geolocation():
    probabilities=np.zeros((10,10),dtype='float32')
    probabilities[1:4,1:4]=.8
    probabilities[8,8]=.9
    transform=from_origin(70,20,.001,.001)
    unfiltered,_,raw=_polygonize(probabilities,.5,transform,'EPSG:4326',{}, {},0)
    filtered,_,clean=_polygonize(probabilities,.5,transform,'EPSG:4326',{}, {},2)
    assert len(unfiltered['features'])==2
    assert len(filtered['features'])==1
    assert clean['positive_pixel_count']==9
    assert clean['cleanup']['removed_pixels']==1
    assert clean['cleanup']['removed_components']==1
    assert filtered['features'][0]['geometry']==unfiltered['features'][0]['geometry']
    assert clean['geometry_metrics']['area_km2']<raw['geometry_metrics']['area_km2']
    empty,_,meta=_polygonize(probabilities,.5,transform,'EPSG:4326',{}, {},10)
    assert empty['features']==[]
    assert meta['geometry_metrics']['area_km2'] is None
