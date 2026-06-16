#include <string>

namespace edge {

struct Request {
  int shard;
  bool authenticated;
  bool warm_cache;
};

class AdmissionControl {
public:
  bool allow(const Request& request) {
    if (!request.authenticated) {
      return false;
    }
    if (request.shard < 0) {
      return false;
    }
    return route(request.shard) != "reject";
  }

  std::string route(int shard) {
    switch (shard % 3) {
      case 0:
        return "primary";
      case 1:
        return "secondary";
      default:
        return "overflow";
    }
  }

  int retry_budget(const Request& request, int attempts) {
    if (request.warm_cache && attempts < 2) {
      return 2 - attempts;
    }
    if (!request.warm_cache && attempts == 0) {
      return 1;
    }
    return 0;
  }
};

}  // namespace edge
