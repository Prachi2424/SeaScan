from __future__ import annotations

import hashlib
import io
import json
import math
import re
import zipfile
from datetime import UTC, datetime
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image as ReportImage,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.schemas.investigation import InvestigationDetail
from app.schemas.report import ReportAnalysisBundle, ReportPackageManifest


LEGAL_NOTICE = (
    "MANDATORY LEGAL NOTICE: This report is an analytical investigative aid generated from the evidence "
    "identified in this document. Candidate rankings indicate statistical and spatio-temporal correlation "
    "only. They do not establish identity, intent, causation, legal responsibility, liability, or guilt. "
    "All findings require independent validation by qualified authorities against original evidence, chain "
    "of custody records, model limitations, environmental uncertainty, and applicable law before any action."
)
MODEL_NOTICE = (
    "Automated outputs may contain false positives, false negatives, geolocation error, AIS gaps or spoofing, "
    "and uncertainty introduced by weather and current observations. Scores are relative investigative leads, "
    "not probabilities of guilt."
)

NAVY = colors.HexColor("#071825")
INK = colors.HexColor("#17303D")
TEAL = colors.HexColor("#148B92")
PALE = colors.HexColor("#E8F5F5")
MUTED = colors.HexColor("#607987")
RED = colors.HexColor("#A52F42")
LINE = colors.HexColor("#C9DADC")


def safe_filename(title: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-").lower() or "investigation"
    return f"seascan-forensic-report-{stem[:64]}.pdf"


def _iter_coordinates(geometry: dict[str, Any] | None) -> Iterable[tuple[float, float]]:
    if not geometry:
        return
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates", [])
    if kind == "Point" and len(coordinates) >= 2:
        yield float(coordinates[0]), float(coordinates[1])
    elif kind in {"LineString", "MultiPoint"}:
        for point in coordinates:
            if len(point) >= 2:
                yield float(point[0]), float(point[1])
    elif kind in {"Polygon", "MultiLineString"}:
        for line in coordinates:
            for point in line:
                if len(point) >= 2:
                    yield float(point[0]), float(point[1])
    elif kind == "MultiPolygon":
        for polygon in coordinates:
            for ring in polygon:
                for point in ring:
                    if len(point) >= 2:
                        yield float(point[0]), float(point[1])


def _feature_geometries(geojson: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not geojson:
        return []
    if geojson.get("type") == "FeatureCollection":
        return [feature.get("geometry", {}) for feature in geojson.get("features", []) if isinstance(feature, dict)]
    if geojson.get("type") == "Feature":
        geometry = geojson.get("geometry")
        return [geometry] if isinstance(geometry, dict) else []
    return [geojson]


def _polygon_rings(geometry: dict[str, Any]) -> Iterable[list[list[float]]]:
    if geometry.get("type") == "Polygon":
        yield from geometry.get("coordinates", [])
    elif geometry.get("type") == "MultiPolygon":
        for polygon in geometry.get("coordinates", []):
            yield from polygon


def _haversine_km(first: tuple[float, float], second: tuple[float, float]) -> float:
    lon1, lat1 = map(math.radians, first)
    lon2, lat2 = map(math.radians, second)
    dlon, dlat = lon2 - lon1, lat2 - lat1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(min(1.0, math.sqrt(value)))


def calculate_spill_metrics(geojson: dict[str, Any] | None) -> dict[str, Any]:
    geometries = _feature_geometries(geojson)
    points = [point for geometry in geometries for point in _iter_coordinates(geometry)]
    if not points:
        return {"component_count": 0, "area_km2": None, "perimeter_km": None, "centroid": None, "bounds": None}
    reference_latitude = sum(point[1] for point in points) / len(points)
    km_per_lon = 111.320 * math.cos(math.radians(reference_latitude))
    area_km2 = 0.0
    perimeter_km = 0.0
    for geometry in geometries:
        for ring in _polygon_rings(geometry):
            if len(ring) < 3:
                continue
            projected = [(float(point[0]) * km_per_lon, float(point[1]) * 110.574) for point in ring]
            signed_area = sum(
                projected[index][0] * projected[(index + 1) % len(projected)][1]
                - projected[(index + 1) % len(projected)][0] * projected[index][1]
                for index in range(len(projected))
            ) / 2
            area_km2 += abs(signed_area)
            perimeter_km += sum(_haversine_km(tuple(ring[index][:2]), tuple(ring[(index + 1) % len(ring)][:2])) for index in range(len(ring)))
    west, east = min(point[0] for point in points), max(point[0] for point in points)
    south, north = min(point[1] for point in points), max(point[1] for point in points)
    return {
        "component_count": len(geometries),
        "area_km2": round(area_km2, 3),
        "perimeter_km": round(perimeter_km, 3),
        "centroid": [round(sum(point[0] for point in points) / len(points), 6), round(sum(point[1] for point in points) / len(points), 6)],
        "bounds": [round(west, 6), round(south, 6), round(east, 6), round(north, 6)],
    }


def _map_png(payload: ReportAnalysisBundle) -> bytes:
    width, height = 1400, 700
    image = Image.new("RGB", (width, height), "#071825")
    draw = ImageDraw.Draw(image, "RGBA")
    layers: list[tuple[str, list[dict[str, Any]], tuple[int, int, int, int]]] = []
    layers.append(("Detected spill", _feature_geometries(payload.spill_geojson), (247, 111, 113, 210)))
    if payload.backward_drift:
        layers.append(("Backward drift", _feature_geometries(payload.backward_drift.trajectory), (82, 218, 224, 230)))
    if payload.forward_drift:
        layers.append(("Forward drift", _feature_geometries(payload.forward_drift.trajectory), (250, 195, 93, 230)))
    if payload.attribution:
        for candidate in payload.attribution.candidates[:3]:
            layers.append((f"AIS {candidate.mmsi}", _feature_geometries(candidate.track_geojson), (155, 137, 255, 190)))
    all_points = [point for _, geometries, _ in layers for geometry in geometries for point in _iter_coordinates(geometry)]
    if not all_points:
        draw.text((60, 70), "No geospatial layers were available for this report.", fill="#9BB5C0", font=ImageFont.load_default())
    else:
        west, east = min(p[0] for p in all_points), max(p[0] for p in all_points)
        south, north = min(p[1] for p in all_points), max(p[1] for p in all_points)
        lon_pad = max((east - west) * 0.12, 0.01)
        lat_pad = max((north - south) * 0.12, 0.01)
        west, east, south, north = west - lon_pad, east + lon_pad, south - lat_pad, north + lat_pad

        def project(point: tuple[float, float]) -> tuple[int, int]:
            x = 70 + int((point[0] - west) / (east - west) * (width - 140))
            y = 50 + int((north - point[1]) / (north - south) * (height - 130))
            return x, y

        for index in range(7):
            x = 70 + index * (width - 140) // 6
            y = 50 + index * (height - 130) // 6
            draw.line((x, 50, x, height - 80), fill=(90, 155, 169, 45), width=1)
            draw.line((70, y, width - 70, y), fill=(90, 155, 169, 45), width=1)
        for label, geometries, color in layers:
            for geometry in geometries:
                kind = geometry.get("type")
                if kind in {"Polygon", "MultiPolygon"}:
                    for ring in _polygon_rings(geometry):
                        projected = [project((float(p[0]), float(p[1]))) for p in ring]
                        if len(projected) >= 3:
                            draw.polygon(projected, fill=(*color[:3], 70), outline=color, width=3)
                else:
                    projected = [project(point) for point in _iter_coordinates(geometry)]
                    if len(projected) > 1:
                        draw.line(projected, fill=color, width=4, joint="curve")
                    for point in projected:
                        draw.ellipse((point[0] - 3, point[1] - 3, point[0] + 3, point[1] + 3), fill=color)
        draw.text((70, height - 56), f"Extent: {west:.4f}, {south:.4f} to {east:.4f}, {north:.4f}", fill="#8CABBA", font=ImageFont.load_default())
    legend_x = 72
    for label, _, color in layers:
        draw.rounded_rectangle((legend_x, 16, legend_x + 12, 28), radius=3, fill=color)
        draw.text((legend_x + 18, 16), label, fill="#DDECEF", font=ImageFont.load_default())
        legend_x += max(150, len(label) * 8 + 44)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _styles() -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("Title", parent=sample["Title"], fontName="Helvetica-Bold", fontSize=25, leading=29, textColor=NAVY, alignment=TA_LEFT, spaceAfter=8),
        "subtitle": ParagraphStyle("Subtitle", parent=sample["Normal"], fontName="Helvetica", fontSize=10, leading=15, textColor=MUTED, spaceAfter=12),
        "h1": ParagraphStyle("H1", parent=sample["Heading1"], fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=NAVY, spaceBefore=10, spaceAfter=8),
        "h2": ParagraphStyle("H2", parent=sample["Heading2"], fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=TEAL, spaceBefore=8, spaceAfter=5),
        "body": ParagraphStyle("Body", parent=sample["BodyText"], fontName="Helvetica", fontSize=9, leading=13, textColor=INK, spaceAfter=7),
        "small": ParagraphStyle("Small", parent=sample["BodyText"], fontName="Helvetica", fontSize=7.5, leading=10, textColor=MUTED),
        "legal": ParagraphStyle("Legal", parent=sample["BodyText"], fontName="Helvetica-Bold", fontSize=8.5, leading=12, textColor=RED, borderColor=colors.HexColor("#E8B5BD"), borderWidth=.7, borderPadding=9, backColor=colors.HexColor("#FFF4F5"), spaceAfter=10),
        "cover": ParagraphStyle("Cover", parent=sample["Normal"], fontName="Helvetica-Bold", fontSize=8, leading=11, textColor=TEAL, alignment=TA_CENTER, spaceAfter=6),
    }


def _value(value: Any, fallback: str = "Not available") -> str:
    if value is None or value == "":
        return fallback
    return str(value)


def _footer(canvas, document) -> None:
    canvas.saveState()
    canvas.setStrokeColor(LINE)
    canvas.line(18 * mm, 14 * mm, 192 * mm, 14 * mm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 9 * mm, "SeaScan | NTRO Problem Statement 26143 | Investigative aid - not a finding of liability")
    canvas.drawRightString(192 * mm, 9 * mm, f"Page {document.page}")
    canvas.restoreState()


def build_forensic_pdf(investigation: InvestigationDetail, payload: ReportAnalysisBundle, generated_at: datetime) -> bytes:
    styles = _styles()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=18 * mm, bottomMargin=20 * mm, title=f"SeaScan Forensic Report - {investigation.title}", author="SeaScan")
    story: list[Any] = []
    report_id = hashlib.sha256(f"{investigation.id}:{generated_at.isoformat()}".encode()).hexdigest()[:16].upper()
    story.extend([
        Paragraph("SEASCAN MARITIME INTELLIGENCE", styles["cover"]),
        Spacer(1, 10 * mm),
        Paragraph("Forensic Oil Spill<br/>Investigation Report", styles["title"]),
        Paragraph("Evidence correlation, drift reconstruction, and explainable vessel candidate ranking", styles["subtitle"]),
        Spacer(1, 8 * mm),
    ])
    metadata = [
        ["Case", investigation.title], ["Investigation ID", investigation.id], ["Report ID", report_id],
        ["Generated (UTC)", generated_at.isoformat()], ["Organization context", "National Technical Research Organisation (NTRO)"],
        ["Problem statement", "26143 - Satellite oil-spill detection and AIS vessel correlation"],
    ]
    meta_table = Table(metadata, colWidths=[40 * mm, 125 * mm])
    meta_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PALE), ("BACKGROUND", (1, 0), (1, -1), colors.white), ("TEXTCOLOR", (0, 0), (0, -1), TEAL), ("TEXTCOLOR", (1, 0), (1, -1), INK), ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTNAME", (1, 0), (1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), .4, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    story.extend([meta_table, Spacer(1, 12 * mm), Paragraph(LEGAL_NOTICE, styles["legal"]), Spacer(1, 18 * mm), Paragraph("Prepared by SeaScan automated analysis pipeline", styles["cover"]), PageBreak()])

    metrics = calculate_spill_metrics(payload.spill_geojson)
    story.extend([Paragraph("1. Executive summary", styles["h1"]), Paragraph(
        f"SeaScan assembled this report from {len(investigation.assets)} persisted evidence asset(s). "
        f"The supplied analysis contains {metrics['component_count']} detected spill component(s), "
        f"{_value(payload.attribution.candidate_count if payload.attribution else None, 'no completed')} vessel candidate ranking(s), "
        f"and {'a completed' if payload.backward_drift else 'no completed'} backward drift reconstruction.", styles["body"]),
        Paragraph(LEGAL_NOTICE, styles["legal"]),
        Paragraph("2. Geospatial evidence map", styles["h1"]),
        ReportImage(io.BytesIO(_map_png(payload)), width=174 * mm, height=87 * mm),
        Paragraph("Figure 1. Evidence overview generated from the report payload. The diagram is not a navigational chart and does not include a basemap.", styles["small"]),
        Paragraph("3. Spill geometry metrics", styles["h1"]),
    ])
    metric_rows = [
        ["Metric", "Value"], ["Detected components", metrics["component_count"]],
        ["Estimated planar area", f"{metrics['area_km2']} km2" if metrics["area_km2"] is not None else "Not available"],
        ["Estimated perimeter", f"{metrics['perimeter_km']} km" if metrics["perimeter_km"] is not None else "Not available"],
        ["Coordinate centroid", ", ".join(map(str, metrics["centroid"])) if metrics["centroid"] else "Not available"],
        ["Bounding extent", ", ".join(map(str, metrics["bounds"])) if metrics["bounds"] else "Not available"],
        ["Positive raster pixels", _value((payload.satellite_validation or {}).get("positive_pixel_count"))],
        ["Segmentation threshold", _value((payload.satellite_validation or {}).get("threshold"))],
    ]
    story.extend([_data_table(metric_rows, [64 * mm, 100 * mm]), Paragraph("Area and perimeter are approximate local planar/geodesic calculations from the supplied GeoJSON and must be validated against source CRS and survey-grade tooling.", styles["small"]), PageBreak()])

    story.extend([Paragraph("4. Drift reconstruction", styles["h1"])])
    drift_rows = [["Run", "Observed at", "Duration", "Particles", "Output features"]]
    for label, drift in (("Backward hindcast", payload.backward_drift), ("Forward forecast", payload.forward_drift)):
        if drift:
            drift_rows.append([label, _value(drift.seed.get("observed_at")), f"{_value(drift.seed.get('duration_hours'))} h", _value(drift.seed.get("particle_count")), len(drift.trajectory.get("features", []))])
        else:
            drift_rows.append([label, "Not completed", "-", "-", "-"])
    story.extend([_data_table(drift_rows, [34 * mm, 49 * mm, 27 * mm, 26 * mm, 29 * mm]), Paragraph("Backward and forward trajectories are simulations conditioned on uploaded environmental observations and configured particle parameters; they are not direct observations.", styles["small"]), Paragraph("5. Potential vessel rankings", styles["h1"])])
    candidate_rows = [["Rank", "MMSI", "Vessel type", "Evidence score", "Closest distance", "AIS positions"]]
    if payload.attribution and payload.attribution.candidates:
        for index, candidate in enumerate(payload.attribution.candidates[:10], start=1):
            candidate_rows.append([index, candidate.mmsi, _value(candidate.vessel_type, "Unrecorded"), f"{candidate.evidence_score:.3f}", f"{_value(candidate.evidence.get('closest_observed_distance_km'))} km", _value(candidate.evidence.get("positions_in_time_window"))])
    else:
        candidate_rows.append(["-", "No completed attribution", "-", "-", "-", "-"])
    story.extend([_data_table(candidate_rows, [15 * mm, 30 * mm, 31 * mm, 28 * mm, 34 * mm, 27 * mm]), Paragraph(payload.attribution.disclaimer if payload.attribution else "No vessel attribution result was supplied.", styles["legal"]), Paragraph("Scoring components", styles["h2"])])
    if payload.attribution:
        weights = [["Component", "Weight"]] + [[name.replace("_", " ").title(), f"{weight:.0%}"] for name, weight in payload.attribution.scoring_formula.items()]
        story.append(_data_table(weights, [90 * mm, 74 * mm]))
    story.extend([PageBreak(), Paragraph("6. Evidence provenance and package integrity", styles["h1"])])
    evidence_rows = [["Type", "Original filename", "Bytes", "SHA-256"]]
    for asset in investigation.assets:
        evidence_rows.append([asset.asset_type.title(), asset.original_filename, f"{asset.byte_size:,}", asset.sha256])
    if not investigation.assets:
        evidence_rows.append(["-", "No persisted evidence assets", "-", "-"])
    story.extend([_data_table(evidence_rows, [24 * mm, 47 * mm, 21 * mm, 73 * mm], font_size=6.5), Paragraph("The package manifest includes the complete PDF SHA-256 digest. Evidence hashes above identify bytes received and persisted by SeaScan; chain-of-custody controls outside this system remain the responsibility of the investigating authority.", styles["small"]), Paragraph("7. Methodology and limitations", styles["h1"]), Paragraph("The pipeline detects candidate slick geometry from configured model inference, uses uploaded wind/current observations for particle advection, reconstructs AIS traffic around the estimated origin window, filters unrelated tracks, and computes a transparent weighted evidence score.", styles["body"]), Paragraph(MODEL_NOTICE, styles["legal"]), Paragraph("8. Mandatory legal disclaimer", styles["h1"]), Paragraph(LEGAL_NOTICE, styles["legal"]), Paragraph("End of report", styles["cover"]),
    ])
    document.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()


def _data_table(rows: list[list[Any]], widths: list[float], font_size: float = 8) -> Table:
    body_style = ParagraphStyle("Cell", fontName="Helvetica", fontSize=font_size, leading=font_size + 2, textColor=INK)
    prepared = [
        [str(cell) if row_index == 0 else Paragraph(str(cell), body_style) for cell in row]
        for row_index, row in enumerate(rows)
    ]
    table = Table(prepared, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, 0), font_size), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F8F8")]), ("GRID", (0, 0), (-1, -1), .35, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return table


def build_report_package(investigation: InvestigationDetail, payload: ReportAnalysisBundle) -> tuple[str, bytes, ReportPackageManifest]:
    generated_at = datetime.now(UTC)
    filename = safe_filename(investigation.title)
    report = build_forensic_pdf(investigation, payload, generated_at)
    manifest = ReportPackageManifest(
        schema_version="1.0",
        report_filename=filename,
        report_sha256=hashlib.sha256(report).hexdigest(),
        generated_at=generated_at.isoformat(),
        investigation_id=investigation.id,
        evidence_assets=[{"id": asset.id, "type": asset.asset_type, "filename": asset.original_filename, "byte_size": asset.byte_size, "sha256": asset.sha256} for asset in investigation.assets],
        legal_notice=LEGAL_NOTICE,
    )
    return filename, report, manifest


def package_zip(filename: str, report: bytes, manifest: ReportPackageManifest) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(filename, report)
        archive.writestr("manifest.json", json.dumps(manifest.model_dump(), indent=2, sort_keys=True))
        archive.writestr("LEGAL_NOTICE.txt", LEGAL_NOTICE + "\n\n" + MODEL_NOTICE + "\n")
    return output.getvalue()
