.PHONY: help test calibrate demo serve lint clean

help:
	@echo "test       lance la suite de tests"
	@echo "calibrate  verifie l'instrument sur corpus a divergence connue"
	@echo "demo       produit un rapport de demonstration (corpus synthetique)"
	@echo "serve      lance l'interface web sur http://127.0.0.1:5000"
	@echo "clean      supprime les sorties generees"

test:
	python3 -m unittest discover -s tests -t . -v

calibrate:
	python3 -m prisme.cli calibrate

demo:
	python3 -m prisme.cli demo --out out

serve:
	python3 -m prisme.cli serve

clean:
	rm -rf out .prisme-cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
