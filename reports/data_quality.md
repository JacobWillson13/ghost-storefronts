# Data quality report

Generated 2026-10-23T18:02:31.573598+00:00

## Silver inspections by source

| source | docs | first | last | with_bbl | with_location | with_nta | with_business_key | storefront_share |
|---|---|---|---|---|---|---|---|---|
| archive | 995,500 | 2010-01-01 | 2023-06-30 | 93.0% | 93.9% | 93.9% | 94.6% | 92.5% |
| live | 286,543 | 2023-07-03 | 2026-08-23 | 96.8% | 99.9% | 95.3% | 96.8% | 97.7% |


## Inspections and closures by year

| year | inspections | closures | closure_rate |
|---|---|---|---|
| 2010 | 76,916 | 3,284 | 4.3% |
| 2011 | 86,833 | 4,298 | 4.9% |
| 2012 | 90,110 | 2,646 | 2.9% |
| 2013 | 84,928 | 4,127 | 4.9% |
| 2014 | 74,374 | 4,742 | 6.4% |
| 2015 | 76,414 | 6,779 | 8.9% |
| 2016 | 85,180 | 8,161 | 9.6% |
| 2017 | 81,690 | 7,460 | 9.1% |
| 2018 | 71,897 | 9,011 | 12.5% |
| 2019 | 69,073 | 9,487 | 13.7% |
| 2020 | 39,462 | 3,807 | 9.6% |
| 2021 | 50,509 | 4,634 | 9.2% |
| 2022 | 72,497 | 5,956 | 8.2% |
| 2023 | 69,950 | 11,274 | 16.1% |
| 2024 | 100,802 | 15,065 | 14.9% |
| 2025 | 92,481 | 15,799 | 17.1% |
| 2026 | 58,927 | 8,842 | 15.0% |


## Outcomes by source

| source | outcome | n |
|---|---|---|
| archive | compliant | 571,503 |
| archive | violation | 232,101 |
| archive | out_of_business | 78,976 |
| archive | no_activity | 39,367 |
| archive | warning | 36,083 |
| archive | closed_at_visit | 22,478 |
| archive | administrative | 8,442 |
| archive | unable | 6,327 |
| archive | padlocked | 223 |
| live | compliant | 96,616 |
| live | violation | 59,443 |
| live | out_of_business | 46,396 |
| live | no_activity | 43,864 |
| live | closed_at_visit | 23,057 |
| live | warning | 7,314 |
| live | administrative | 6,396 |
| live | padlocked | 1,757 |
| live | unable | 1,700 |


## results with no crosswalk entry

Add these to `config/outcome_crosswalk.yaml`.


_none_


## industries in the default group

Add these to `config/industry_crosswalk.yaml` (groups, renames, non_storefront).


| source | label | n | is_storefront |
|---|---|---|---|
| archive | Tow Truck Company | 17,710 | False |
| archive | Mobile Food Vendor | 16,863 | False |
| archive | Pedicab Business | 11,395 | False |
| archive | General Vendor | 10,013 | False |
| archive | Home Improvement Contractor | 6,114 | False |
| archive | Sightseeing Bus | 4,576 | False |
| archive | Tow Truck Driver | 3,055 | False |
| live | Tow Truck Company | 2,686 | False |
| archive | Horse Drawn Cab Owner | 2,606 | False |
| archive | Other | 1,322 | True |
| live | Pedicab Business | 1,286 | False |
| archive | Pedicab Driver | 1,062 | False |
| live | Sightseeing Bus | 1,035 | False |
| live | Mobile Food Vendor | 755 | False |
| archive | Misc Archived | 734 | True |
| live | Horse Drawn Cab Owner | 609 | False |
| archive |  | 406 | False |
| archive | Gasoline Truck-Retail | 404 | False |
| archive | Government Agency Retail | 392 | True |
| archive | Home Improvement Salesperson | 229 | False |
| archive | Amusement Device (Portable) | 156 | False |
| live | Home Improvement Contractor | 103 | False |
| live | Gasoline Truck-Retail | 92 | False |
| archive | H05 | 63 | True |
| live | General Vendor | 62 | False |
| archive | Amusement Device (Temporary) | 60 | False |
| archive | H25 | 52 | True |
| archive | Temporary Street Fair Vendor Permit | 51 | False |
| archive | H70 | 51 | True |
| archive | Auctioneer | 36 | False |
| archive | H15 | 35 | True |
| archive | Mailorder Misc | 34 | False |
| live | Pedicab Driver | 34 | False |
| archive | Auto Dealership | 24 | True |
| archive | Internet Complaints | 23 | True |
| archive | Hotel/Motel | 23 | True |
| archive | Horse Drawn Cab Driver | 20 | True |
| live | Airline | 18 | True |
| live | Government Agency Retail | 17 | True |
| archive | Booting Company | 12 | True |
| archive | Process Server (Individual) | 11 | True |
| live | Hotel/Motel | 10 | True |
| archive | Bail Bonds | 10 | True |
| archive | Games Of Chance | 9 | True |
| live | Booting Company | 9 | True |
| archive | Process Server (Organization) | 8 | True |
| archive | H06 | 7 | True |
| archive | Auto Leasing | 6 | True |
| archive | Sightseeing Guide | 6 | False |
| archive | Locksmith Apprentice | 5 | True |
| archive | Motion Picture Projectionist | 5 | True |
| archive | 053 | 4 | True |
| archive | Debt Settlement | 4 | True |
| archive | H10 | 4 | True |
| live | Pregnancy Service Center (PSC) | 4 | True |
| archive | H27 | 4 | True |
| archive | Distress Prop Consultants | 3 | True |
| archive | Tickets-Live Perf | 3 | True |
| archive | H29 | 3 | True |
| archive | General Vendor Distribution | 3 | True |
| live | Car Rental | 3 | True |
| archive | 117 | 2 | True |
| archive | I & | 2 | True |
| live | Industrial Laundry Delivery | 2 | True |
| live | Auto Dealership | 2 | True |
| archive | 420 | 2 | True |
| archive | H98 | 2 | True |
| archive | Pregnancy Service Center (PSC) | 2 | True |
| archive | H86 | 2 | True |
| archive | Motion Picture Operator | 2 | True |
| archive | H92 | 2 | True |
| archive | H99 | 1 | True |
| archive | 114 | 1 | True |
| archive | 372 | 1 | True |
| archive | 873 | 1 | True |
| archive | H03 | 1 | True |
| live |  | 1 | False |
| archive | H01 | 1 | True |
| archive | 009 | 1 | True |
| archive | H90 | 1 | True |


## Industry groups by source

| group | source | n |
|---|---|---|
| auto_fuel_parking | archive | 57,197 |
| auto_fuel_parking | live | 17,598 |
| entertainment | archive | 1,186 |
| entertainment | live | 66 |
| food_grocery | archive | 204,749 |
| food_grocery | live | 56,803 |
| general_retail | archive | 194,751 |
| general_retail | live | 41,142 |
| lodging | live | 1,425 |
| missing | archive | 406 |
| missing | live | 1 |
| other | archive | 77,236 |
| other | live | 6,727 |
| personal_services | archive | 129,202 |
| personal_services | live | 25,719 |
| product_rule_checks | archive | 11,135 |
| product_rule_checks | live | 65 |
| secondhand_pawn | archive | 56,700 |
| secondhand_pawn | live | 9,428 |
| tobacco_vape_cannabis | archive | 261,608 |
| tobacco_vape_cannabis | live | 127,332 |
| wholesale_industrial | archive | 1,330 |
| wholesale_industrial | live | 237 |


## Storefront cardinality (storefront industries only)

| inspections | storefronts | businesses |
|---|---|---|
| 1,200,604 | 77,369 | 227,352 |


## Cross-system continuity (exact business_key)

Open archive businesses seen from July 2022 on, and how many the live system finds under the same key. A low rate means the key is splitting businesses across the June 2023 system switch.


| open_archive_businesses_2022h2_plus | found_in_live | match_rate |
|---|---|---|
| 18,290 | 14,220 | 77.7% |


## Sample lineage

| sample_docs | archive_docs_flagged |
|---|---|
| 80,047 | 80,040 |


## Duplicate natural keys in raw data

Archive `rec_id` repeats are expected: it is a case number shared by re-inspections. Silver keys on the raw row hash, so nothing collapses.


| archive_rec_id | live_inspection_number |
|---|---|
| 9,046 | 0 |


## Live address types (decides the non-storefront rule)

| address_type | n |
|---|---|
| Complete Address | 279,862 |
| Cross Street (Intersection) | 6,563 |
| Place (Landmark) | 113 |
|  | 4 |
| P.O. Box | 1 |


## Live inspection types

| inspection_type | n |
|---|---|
| Patrol | 101,839 |
| Tobacco - Sale to Minor | 46,493 |
| Tobacco - Adult Inspection | 39,322 |
| Tobacco - T21 | 32,762 |
| Scale | 20,249 |
| Business Education | 13,107 |
| Consumer Request to Inspect | 8,065 |
| WAM - Petroleum | 7,460 |
| Sweep | 3,283 |
| Qualifying Renewal Vehicle | 2,270 |
| Check UNL - FTR | 2,205 |
| Sealing Order Follow-up | 1,967 |
| Compliance | 1,557 |
| License Suspended | 908 |
| Legal Case-Related | 846 |
| Qualifying - Vehicle | 731 |
| Scale - Condemned Follow-up | 509 |
| Qualifying - Site | 478 |
| Mediation | 424 |
| License Revoked | 421 |
| Sealing Order | 365 |
| External to DCA - External Agencies | 297 |
| WAM - Other | 295 |
| Tobacco - State Suspension | 165 |
| External to DCA - Public Official | 147 |
| External to DCA - Community Board | 117 |
| Business Info Check | 87 |
| Program Participant DARP | 42 |
| Program Participant DARP-ROTOW | 30 |
| Price Gouging | 30 |
| WAM - Condemned Follow-up | 29 |
| Program Participant ROTOW | 28 |
| License Suspended - Adjudication | 14 |
| Check UNL | 1 |
