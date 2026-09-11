#include "sessions.h"

#include <esp_random.h>

uint32_t sessionOpen(SessionTable& t, const uint8_t* payload, uint8_t len) {
    if (len > SESSION_PAYLOAD) len = SESSION_PAYLOAD;

    uint8_t pick = 0;
    bool found_free = false;
    for (uint8_t i = 0; i < SESSION_SLOTS; i++) {
        if (t.slots[i].sid == 0) { pick = i; found_free = true; break; }
    }
    if (!found_free) {
        // Every slot is pending: drop the one opened longest ago. A flood of
        // /init still cannot reach past SESSION_SLOTS legitimate sessions.
        uint32_t oldest = t.slots[0].seq;
        for (uint8_t i = 1; i < SESSION_SLOTS; i++) {
            if (t.slots[i].seq < oldest) { oldest = t.slots[i].seq; pick = i; }
        }
    }

    uint32_t sid = esp_random();
    if (sid == 0) sid = 1;                      // 0 is the free marker
    t.slots[pick].sid = sid;
    t.slots[pick].seq = t.next_seq++;
    t.slots[pick].len = len;
    memcpy(t.slots[pick].payload, payload, len);
    return sid;
}

bool sessionTake(SessionTable& t, uint32_t sid, uint8_t* out, uint8_t len) {
    if (sid == 0) return false;
    for (uint8_t i = 0; i < SESSION_SLOTS; i++) {
        if (t.slots[i].sid != sid) continue;
        if (t.slots[i].len != len) return false;
        memcpy(out, t.slots[i].payload, len);
        t.slots[i].sid = 0;                     // single use
        return true;
    }
    return false;
}

void sessionReset(SessionTable& t) {
    for (uint8_t i = 0; i < SESSION_SLOTS; i++) t.slots[i].sid = 0;
    t.next_seq = 1;
}
