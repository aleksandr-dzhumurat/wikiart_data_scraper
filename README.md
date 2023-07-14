# wikiart_data_scraper

Scrape wikiart.org. Get artists + content

Run craper for wikiart.org

```shell
PIPELINE=wikidata make run
```

# Scrape galleries

Find a link to a city

![galleries_list](assets/galleries_list.png)

Update YML config with selected links then run collector

```shell
PIPELINE=galleries make run
```

# Work in progress

Refactor code with [multiprocessing](https://www.zenrows.com/blog/speed-up-web-scraping-with-concurrency-in-python#concurrency)
