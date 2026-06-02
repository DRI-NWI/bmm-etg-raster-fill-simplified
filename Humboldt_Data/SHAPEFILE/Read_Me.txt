SHAPEFILE
-------------------
This directory contains the shapefile that was used for processing and producing net ET estimates.  All polygons in the shapefile are considered to be within the discharge area.  Data was processed sequentially, by HA (hydrographic area).  Due to the methodology employed, discharge areas that overlap more than one HA are split at the HA boundary.  This results in some polygons exhibiting discontinuity from adjacent segment.

This dataset was produced through the modification of previously established phreatophyte discharge boundaries.  The development of the this shapefile was based on remote sensing data and field examinations.  Boundaries were modified using the best judgment of individual team members and subjected to internal review.  

(Note: In this shapefile, the designation of “irrigated cropland” is defined as a highly managed, irrigated area that exhibits higher net ET than surrounding areas)


FIELDS:
-------------------
FID - Feature ID
Type - Landcover Type
ACRES - Area in Acres
HYD_AREA_N - Hydrologic Area name
SUBAREA_NA - Hydrologic Sub-Area name
BASIN - Basin identifier used for data processing (comprised of HYD_AREA and HYD_AREA_N )
HYD_AREA - Hydrologic Area number
Fixed_ETg - Fixed rate of ETg (net ET) used as a substitute for areas of "irrigated cropland".  Values of 0 are not used for subsitution.
ACRES - Calculated area in acres
Inside_Dis - Flag used to denote whether the polygon is inside or outside the groundwater discharge area
ETg_ScaleF - This field is used to scale the ETg (net ET) estimated for areas classified as "Meadow."  The factor compensates for the influence of irrigation on the unit of land.