// Pending-authentication sessions, keyed by a random session identifier.
//
// The first implementation kept one pending session per protocol and consumed
// it on any request to /verify, authentic or not. An attacker who posted
// garbage between a peer's two requests cancelled that peer's session -- the
// opposite of the reference paper's claim that no resource is assigned before
// authentication, so denial of service is not possible.
//
// A session now carries a 32-bit identifier drawn from the hardware RNG and
// returned by /init. A /verify consumes only the slot whose identifier it
// presents, so a request that does not hold one cannot disturb a peer that
// does. Several slots exist so that an attacker calling /init cannot evict a
// legitimate pending session either, up to the number of slots.
//
// Lookup and eviction happen outside every PhaseTimer, so none of this appears
// in the measured cryptographic cost.
#pragma once

#include <stdint.h>
#include <string.h>

constexpr uint8_t SESSION_SLOTS = 4;
constexpr uint8_t SESSION_PAYLOAD = 32;   // the largest protocol state (ECC's challenge)

struct SessionTable {
    struct Slot {
        uint32_t sid = 0;                 // 0 means free
        uint32_t seq = 0;                 // open order, for evicting the oldest
        uint8_t payload[SESSION_PAYLOAD] = {0};
        uint8_t len = 0;
    } slots[SESSION_SLOTS];
    uint32_t next_seq = 1;
};

// Stores `len` bytes and returns the session identifier the caller must hand
// back. Never returns 0. Takes a free slot, else the oldest one.
uint32_t sessionOpen(SessionTable& t, const uint8_t* payload, uint8_t len);

// Consumes the slot holding `sid`, copying its payload out. Returns false and
// changes nothing if no slot holds that identifier.
bool sessionTake(SessionTable& t, uint32_t sid, uint8_t* out, uint8_t len);

// Frees every slot. Used by POST /api/reset.
void sessionReset(SessionTable& t);
