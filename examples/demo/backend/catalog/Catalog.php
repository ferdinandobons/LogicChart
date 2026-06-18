<?php

namespace Catalog;

class Catalog
{
    public function reorderQuantity(string $availability, int $onHand): int
    {
        switch ($availability) {
            case "in_stock":
                return 0;
            case "low_stock":
                return $this->restockTarget($onHand) - $onHand;
            case "out_of_stock":
                return $this->restockTarget($onHand);
            case "discontinued":
                return 0;
            default:
                return 0;
        }
    }

    public function merchandisingAction(string $availability, bool $featured): string
    {
        if ($featured && $availability === "low_stock") {
            return "promote_with_limit";
        }
        if ($availability === "out_of_stock") {
            return "hide";
        }
        if ($availability === "discontinued") {
            return "archive";
        }
        return "promote";
    }

    private function restockTarget(int $onHand): int
    {
        if ($onHand < 0) {
            return 150;
        }
        return 100;
    }
}
