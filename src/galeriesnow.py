import os
from typing import Optional, List
import requests
import re

import pandas as pd
from bs4 import BeautifulSoup


def extract_txt_description(scraper):
  rows = scraper.find_all(name='div', class_='row')
  res = []
  for row in rows:
    t = row.find('p')
    if t is not None:
      if len(t.text) > 150:
        precessed_txt =  ''.join([
            i for i in t.text.splitlines() if len(i) > 0
        ])
        res.append(precessed_txt)
  res = ' '.join(res)
  return {'exhibition_description': res}

def extract_artist(scraper):
  prefix = 'https://www.galleriesnow.net'
  m = scraper.find_all(name='div', class_='col-md-8')
  res = {}
  for i in m:
    t = i.find_all('p')
    if t is not None:
      for p in t:
        if 'Artist' in p.text:
          g = p.find('a')
          if g is not None:
            link = g['href']
            res.update({'artist_name': g.text, 'artist_link': f'{prefix}{link}'})
  return res

def get_exhibition_description(exhibition_url):
    res = {}
    galery_web_page = requests.get(exhibition_url)
    galery_scraper = BeautifulSoup(markup=galery_web_page.content, features="html.parser")
    res.update(extract_artist(galery_scraper))
    res.update(extract_txt_description(galery_scraper))
    return res

def get_exhibitions(url: str, output_csv_path: str) -> pd.DataFrame:
    if not os.path.exists(output_csv_path):
        artwork_web_page = requests.get(url)
        galleries_scraper = BeautifulSoup(markup=artwork_web_page.content, features="html.parser")
        galleries_block = galleries_scraper.find(name='ul', class_='contentul')

        img_iter = galleries_block.find_all(name='li')
        cnt = 0
        batch_size = 5
        res = []
        for i in img_iter:
        cur_exhibition = {'galery_name' : i['data-gallery-name']}
        g = i.find(name='div', class_='panel-body')
        link = g.find('a')
        if link is not None:
            cur_exhibition.update({'exhibition_link': link['href']})
            cur_exhibition.update(get_exhibition_description(link['href']))
            t = g.find(name='div', class_='extb-1')
            if t is not None:
            exhibition_link = t.find('a')
            if exhibition_link is not None:
                cur_exhibition.update({'exhibition_name': exhibition_link.text})
            addr = t.find(name='div', class_='space_address')
            if addr is not None:
                cur_exhibition.update({'galery_adress':  addr.text.strip()})
            open_hours = t.find(name='div', class_='d-block')
            if open_hours is not None:
                cur_exhibition.update({'open hours':  open_hours.text.strip()})
            res.append(cur_exhibition)
            cnt += 1
            if cnt % batch_size == 0:
            print('%d saved' % cnt)
        # saving data
        pd.json_normalize(res).to_csv(output_csv_path, index=False)
    logger.info('Data collected: %s', output_csv_path)
    return df

def gallerty_images(url: str) -> Optional[List]:
  galery_web_page = requests.get(url)
  gallery_scraper = BeautifulSoup(markup=galery_web_page.content, features="html.parser")
  t = gallery_scraper.find_all(class_='slick-image-slide')
  res = []
  for tt in t:
    img = tt.find(class_='ex_fullimg')
    pattern = r"url\('(\S+)'\)"
    res.append(re.search(pattern, img['style']).group(1))
  if len(res) == 0:
    res = None
  return res

def get_galleries(url: str, input_csv_path: str, output_csv_path: str):
    artwork_web_page = requests.get(url)
    galleries_scraper = BeautifulSoup(markup=artwork_web_page.content, features="html.parser")
    galleries_block = galleries_scraper.find(name='ul', class_='contentul')

    img_iter = galleries_block.find_all(name='li')
    cnt = 0
    batch_size = 5
    res = []
    for i in img_iter:
        cur_exhibition = {'galery_name' : i['data-gallery-name']}
        if i['data-gallery-name'] not in [i['galery_name'] for i in res]:
            d = i.find(class_='panel-heading')
            if d is not None:
                gallery_link = d.find('a')['href']
                gallery_imgs = gallerty_images(gallery_link)
                cur_exhibition.update({'gallery_link': gallery_link, 'gallery_imgs': gallery_imgs})
            res.append(cur_exhibition)
    (
        pd
        .json_normalize(res)
        .to_csv(output_csv_path, index=False)
    )

def merge_data(exhibitions_data_path: str, galleries_data_path: str, result_csv: str):
    exhibitions_df = pd.read_csv(exhibitions_data_path)
    galleries_df = pd.read_csv(galleries_data_path)
    (
        exhibitions_df
        .merge(galleries_df, how='left', on='galery_name')
        .to_csv(output_csv_path, index=False)
    )
