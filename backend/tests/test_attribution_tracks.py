import json
import pandas as pd
import pytest
from app.ais.attribution import rank_candidates

FIELDS={name:name for name in ['mmsi','timestamp','latitude','longitude','speed_knots','course_degrees']}
def rank(tmp_path,rows,**kwargs):
    path=tmp_path/'tracks.csv'
    pd.DataFrame(rows,columns=list(FIELDS)).to_csv(path,index=False)
    excluded=[]
    result=rank_candidates(path,{'field_mapping':FIELDS},origin_latitude=0,origin_longitude=0,estimated_origin_at='2020-01-01T12:00:00Z',search_radius_km=.2,temporal_window_minutes=5,behavior_window_hours=24,exclusions=excluded,**kwargs)
    json.dumps(result,allow_nan=False)
    return result,excluded


def test_interpolated_crossing_without_in_window_observations(tmp_path):
    rows=[[123456789,'2020-01-01T11:50:00Z',0,-.01,4,90],[123456789,'2020-01-01T12:10:00Z',0,.01,4,90]]
    results,excluded=rank(tmp_path,rows)
    assert len(results)==1 and not excluded
    evidence=results[0]['evidence']
    assert evidence['closest_approach_interpolated']
    assert evidence['positions_in_time_window']==0
    assert evidence['closest_observed_distance_km'] is None
    assert evidence['closest_approach_distance_km']==pytest.approx(0,abs=1e-4)
    assert results[0]['score_breakdown']['temporal']==1


def test_long_gap_does_not_create_a_crossing(tmp_path):
    result,excluded=rank(tmp_path,[[123456789,'2020-01-01T10:00:00Z',0,-.01,None,None],[123456789,'2020-01-01T14:00:00Z',0,.01,None,None]])
    assert result==[]
    assert excluded[0]['unsupported_segments']==1


def test_single_position_serializes_without_infinity(tmp_path):
    result,_=rank(tmp_path,[[123456789,'2020-01-01T12:00:00Z',0,0,None,None]])
    assert result[0]['evidence']['maximum_ais_gap_minutes'] is None
    assert result[0]['evidence']['behavior']['speed_drop'] is None


def test_envelope_and_heading_are_explicit(tmp_path):
    region={'type':'Feature','geometry':{'type':'Polygon','coordinates':[[[-.001,-.001],[.001,-.001],[.001,.001],[-.001,.001],[-.001,-.001]]]},'properties':{}}
    result,_=rank(tmp_path,[[123456789,'2020-01-01T11:50:00Z',0,-.01,4,90],[123456789,'2020-01-01T12:10:00Z',0,.01,4,90]],origin_region=region,release_heading=90)
    evidence=result[0]['evidence']
    assert evidence['origin_region_intersection'] is True
    assert evidence['heading_alignment']==pytest.approx(1)


def test_message_count_does_not_inflate_temporal_score(tmp_path):
    rows=[[123456789,'2020-01-01T12:02:00Z',0,0,None,None]]
    first,_=rank(tmp_path,rows)
    repeated,_=rank(tmp_path,rows*10)
    assert first==repeated
    assert first[0]['score_breakdown']['temporal']==pytest.approx(.6)
