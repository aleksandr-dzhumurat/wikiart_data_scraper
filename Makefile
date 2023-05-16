CURRENT_DIR = $(shell pwd)
PROJECT_NAME = artinder

build:
	docker build -t ${PROJECT_NAME}:dev .

run:
	docker run -it --rm \
	    --env-file ${CURRENT_DIR}/.env \
	    -p ${PORT}:8888 \
	    -v "${CURRENT_DIR}/src:/srv/src" \
	    -v "${CURRENT_DIR}/data:/srv/data" \
	    --name ${PROJECT_NAME}_container \
	    ${PROJECT_NAME}:dev scrape

run-debug:
	docker run -it --rm \
	    --env-file ${CURRENT_DIR}/.env \
	    -v "${CURRENT_DIR}/src:/srv/src" \
	    -v "${CURRENT_DIR}/data:/srv/data" \
	    --name ${PROJECT_NAME}_container \
	    ${PROJECT_NAME}:dev bash

stop:
	docker rm -f techcrunch_scraper