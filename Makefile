.PHONY: all clean venv build upload monitor benchmark test-security test-native smoke-test

# Forward all targets to the ESP32_Auth_PIO directory
%:
	$(MAKE) -C ESP32_Auth_PIO $@

all:
	$(MAKE) -C ESP32_Auth_PIO all
