#include <stddef.h>

typedef enum {
    POLICY_LRU,
    POLICY_LFU,
    POLICY_FIFO,
    POLICY_WEIGHTED
} eviction_policy;

/* Index of the slot to evict for a given policy, or -1 for an empty cache. */
int evict_index(eviction_policy policy, int size, int hot_key_count) {
    if (size <= 0) {
        return -1;
    }
    if (hot_key_count > size / 2) {
        return size - 1;
    }
    switch (policy) {
        case POLICY_LRU:
            return 0;
        case POLICY_LFU:
            return size / 2;
        case POLICY_FIFO:
            return size - 1;
        case POLICY_WEIGHTED:
            return hot_key_count > 0 ? hot_key_count - 1 : 0;
        default:
            return 0;
    }
}
