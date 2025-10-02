.PHONY: test build clean

test:
	python3 test_runner.py

build: clean
	./build.sh

clean:
	rm -rf build dist *.spec
