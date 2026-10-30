# Compila en el PC la lógica y la interfaz del firmware (sin ESP32) para tests y capturas.
#   make -C tools/host test            → tests de la lógica
#   make -C tools/host preview OUT=dir → PNG de cada pantalla
ROOT := ../..
ARDUINOJSON ?= $(HOME)/Arduino/libraries/ArduinoJson/src
BUILD ?= /tmp/esp32-host-build
CXXFLAGS := -std=c++17 -O1 -g -Wall -Wextra -Wno-unused-parameter -Wno-maybe-uninitialized -Wno-format-truncation -I$(ROOT)/src -isystem $(ARDUINOJSON) -DHOST_BUILD
SRC := $(ROOT)/src/gfx/scene.cpp $(ROOT)/src/gfx/font.cpp $(ROOT)/src/core/util.cpp \
       $(ROOT)/src/model/calendar.cpp $(ROOT)/src/model/lists.cpp $(ROOT)/src/model/pomodoro.cpp \
       $(ROOT)/src/model/media.cpp $(ROOT)/src/model/notes.cpp $(ROOT)/src/app/protocol.cpp $(ROOT)/src/ui/ui.cpp $(ROOT)/src/ui/screens.cpp \
       platform_host.cpp
OUT ?= $(BUILD)/capturas

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/preview: $(BUILD) preview.cpp $(SRC) $(wildcard $(ROOT)/src/*/*.h)
	$(CXX) $(CXXFLAGS) -o $@ preview.cpp $(SRC)

$(BUILD)/tests: $(BUILD) tests.cpp $(SRC) $(wildcard $(ROOT)/src/*/*.h)
	$(CXX) $(CXXFLAGS) -fsanitize=address,undefined -o $@ tests.cpp $(SRC)

preview: $(BUILD)/preview
	rm -rf $(OUT) && $(BUILD)/preview $(OUT)

test: $(BUILD)/tests
	$(BUILD)/tests

.PHONY: preview test
