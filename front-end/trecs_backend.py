import os
import re
import warnings
import datetime
import numpy as np
import pandas as pd
from geopy.distance import geodesic


pd.options.mode.chained_assignment = None
warnings.filterwarnings('ignore', category=DeprecationWarning)

"""## Import S3 Bucket Data"""

global s3_df
global zip_codes_df

s3_df = pd.read_csv('s3://trecs-data-s3/data/final/trecs.csv',
                    index_col=0,
                    encoding='unicode_escape',
                    converters={'Zip': str,
                                'Phone Number': str},
                    low_memory=False)

zip_codes_df = pd.read_csv('s3://trecs-data-s3/data/raw_data/zip_centroid_placekey.csv',
                           converters={'zip': str})

zip_codes_df['Zip Integer'] = zip_codes_df['zip'].astype(int)
zip_codes_df = zip_codes_df.groupby('Zip Integer').first().reset_index()
zip_codes_df = zip_codes_df.sort_values(['Zip Integer'], ascending=[True])

zip_cols = {'zip': 'Zip',
            'Zip Integer': 'Zip Integer',
            'placekey': 'Centroid Placekey',
            'latitude': 'Centroid Latitude',
            'longitude': 'Centroid Longitude'}

zip_codes_df = zip_codes_df.rename(columns=zip_cols)

zip_codes_df = zip_codes_df.loc[:, ['Zip',
                                    'Zip Integer',
                                    'Centroid Placekey',
                                    'Centroid Latitude',
                                    'Centroid Longitude']]


def format_s3_df(s3_df):

    '''
    Format S3 data to fill in blanks and create an integer column
    '''

    s3_df.loc[:, 'Zip Integer'] = s3_df.loc[:, 'Zip'].astype(int)
    s3_df['Credential'].fillna('', inplace=True)
    s3_df['Years of Experience'].fillna(0, inplace=True)
    s3_df['Org Name'].fillna('UNKNOWN', inplace=True)

    return s3_df
    

def calculate_distance(lat1, lon1, lat2, lon2):

    '''
    Calculate the distances in miles between two coordinates
    '''

    return geodesic((lat1, lon1), (lat2, lon2)).miles


def get_appropriate_placekey_length(placekey_distance):

    '''
    Return how many placekey characters should be used for distance searching
    '''

    placekey_dict_char = {
        12452.3: 1,
        1725.5 : 2,
        661.8  : 3,
        94.7   : 4,
        13.5   : 5,
        5.1    : 6,
        0.7    : 7,
        0.3    : 8,
        0.0    : 9
    }

    if placekey_distance in placekey_dict_char:

        return int(placekey_dict_char[placekey_distance])

    else:

        return -1


def match_placekey_distance(n):

    '''
    Convert placekey character length to a distance in miles
    '''

    placekey_dict_meters = {
        1: 20040000,
        2: 2777000,
        3: 1065000,
        4: 152400,
        5: 21770,
        6: 8227,
        7: 1176,
        8: 443.2,
        9: 63.47
    }

    meters_to_miles_conversion = 0.000621371

    if n in placekey_dict_meters:

        return float(f'{(placekey_dict_meters[n] * meters_to_miles_conversion):.1f}')

    else:

        return -1


def get_appropriate_placekey_distance(max_distance):

    '''
    Determine how many placekeys should be used for the zip code search
    '''

    if max_distance >= 1725.5:
        distance = match_placekey_distance(1)

    elif max_distance >= 661.8:
        distance = match_placekey_distance(2)

    elif max_distance >= 94.7:
        distance = match_placekey_distance(3)

    elif max_distance >= 13.5:
        distance = match_placekey_distance(4)

    elif max_distance >= 5.1:
        distance = match_placekey_distance(5)

    elif max_distance >= 0.7:
        distance = match_placekey_distance(6)

    elif max_distance >= 0.0:
        distance = match_placekey_distance(7)

    else:
        distance = -1

    return distance


def find_matching_placekeys(placekey, max_distance=25):

    '''
    Filter the S3 data based on a maximum default distance of 25 miles
    '''

    distance_radius = get_appropriate_placekey_distance(max_distance)

    placekey_n_char = get_appropriate_placekey_length(distance_radius)

    matching_rows = s3_df[s3_df['Centroid Placekey'].str[:placekey_n_char] == placekey[:placekey_n_char]]

    return matching_rows

s3_df['Score'].value_counts()


def get_best_doctors(target_zip,
                     priority=['score','distance','experience'],
                     gender_preference='any',
                     top_n=10,
                     unique_doctors=False,
                     max_distance=100):

    '''
    Recommend the top 5 doctors for a given zip code.
    If there are no doctors in that zip code, expand the search
        up to 50 zip codes above and below until a match is found.

    Recommendations are done using a list of priorities, which determine the
        sorting order of the results.
    For example, if one only cares about distance, use priority=['distance']
    '''

    df = format_s3_df(s3_df)

    sorting_mapping_dict = {
        'score': 'Score',
        'distance': 'Distance (miles)',
        'experience': 'Years of Experience'
    }

    sorting_priority = [sorting_mapping_dict[p] for p in priority if p in priority]

    sorting_order_dict = {
        'Score': False,
        'Distance (miles)': True,
        'Years of Experience': False
    }

    try:

        placekey_target_row = zip_codes_df[zip_codes_df['Zip'] == target_zip]
        centroid_target_placekey = placekey_target_row['Centroid Placekey'].values[0]
        centroid_target_latitude = placekey_target_row['Centroid Latitude'].values[0]
        centroid_target_longitude = placekey_target_row['Centroid Longitude'].values[0]

    except IndexError:

        zip_code_int = int(target_zip)

        for i in range(1, 100):

            zip_code_above = zip_code_int + i
            zip_code_below = zip_code_int - i

            try:

                if i % 2 == 0:

                    placekey_target_row_above = zip_codes_df[zip_codes_df['Zip Integer'] == int(zip_code_above)]
                    centroid_target_placekey = placekey_target_row_above['Centroid Placekey'].values[0]
                    centroid_target_latitude = placekey_target_row_above['Centroid Latitude'].values[0]
                    centroid_target_longitude = placekey_target_row_above['Centroid Longitude'].values[0]
                    break

                else:

                    placekey_target_row_below = zip_codes_df[zip_codes_df['Zip Integer'] == int(zip_code_below)]
                    centroid_target_placekey = placekey_target_row_below['Centroid Placekey'].values[0]
                    centroid_target_latitude = placekey_target_row_below['Centroid Latitude'].values[0]
                    centroid_target_longitude = placekey_target_row_below['Centroid Longitude'].values[0]
                    break

            except IndexError:

                pass

        else:

            raise IndexError(f'Zip code {target_zip} and nearby zip codes not found.')

    filtered_df = find_matching_placekeys(centroid_target_placekey)

    filtered_df.loc[:, 'Distance (miles)'] = filtered_df.apply(lambda row:
                                                               calculate_distance(centroid_target_latitude, centroid_target_longitude,
                                                               row['Centroid Latitude'], row['Centroid Longitude']), axis=1)

    selected_columns = ['Oncologist Name','Gender','Years of Experience',
                        'Org Name','Address','Phone Number',
                        'Distance (miles)','Score']

    best_doctors = filtered_df[selected_columns]

    best_doctors.loc[:, 'Score'] = best_doctors.loc[:, 'Score'].astype(int)
    best_doctors.loc[:, 'Years of Experience'] = best_doctors.loc[:, 'Years of Experience'].astype(int)
    best_doctors.loc[:, 'Distance (miles)'] = best_doctors['Distance (miles)'].round(1)
    best_doctors.loc[:, 'Phone Number'] = best_doctors.loc[:, 'Phone Number'].astype(str).apply(lambda x: str(x).split('.')[0])

    if unique_doctors == True:
        best_doctors = best_doctors.sort_values(by='Oncologist Name').drop_duplicates(subset='Oncologist Name', keep='first')

    if gender_preference.upper() == 'M':
        best_doctors = best_doctors.loc[best_doctors['Gender'] == 'M']

    if gender_preference.upper() == 'F':
        best_doctors = best_doctors.loc[best_doctors['Gender'] == 'F']

    sorting_ascending_order = [sorting_order_dict[key] for key in sorting_priority]
    best_doctors = best_doctors.sort_values(sorting_priority, ascending=sorting_ascending_order)

    best_doctors = best_doctors[best_doctors['Distance (miles)'] <= max_distance].head(top_n)

    best_doctors = best_doctors.reset_index(drop=True)
    best_doctors.index = best_doctors.index + 1

    return best_doctors

