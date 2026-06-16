#include <string>

enum class CacheTier {
  Cold,
  Warm,
  Hot,
};

class NativePolicy {
public:
  int ttl(CacheTier tier, bool degraded) {
    if (degraded) {
      return 30;
    }
    switch (tier) {
      case CacheTier::Cold:
        return 60;
      case CacheTier::Warm:
        return 300;
      case CacheTier::Hot:
        return 900;
      default:
        return 120;
    }
  }
};
