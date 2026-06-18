// Package orders models the order lifecycle for the demo backend.
package orders

type Status string

const (
	StatusPending   Status = "pending"
	StatusPaid      Status = "paid"
	StatusShipped   Status = "shipped"
	StatusDelivered Status = "delivered"
	StatusCancelled Status = "cancelled"
)

type Order struct {
	ID          string
	Status      Status
	TotalCents  int
	Expedited   bool
	RiskScore   int
}

// NextAction returns the operational step for an order's current status.
func (o *Order) NextAction() string {
	switch o.Status {
	case StatusPending:
		return o.pendingAction()
	case StatusPaid:
		return o.paidAction()
	case StatusShipped:
		return "track_delivery"
	case StatusDelivered:
		return "request_review"
	case StatusCancelled:
		return "issue_refund"
	default:
		return "manual_review"
	}
}

func (o *Order) FulfillmentPlan(stockAvailable bool, carrierHealthy bool) string {
	if !o.CanFulfill(stockAvailable) {
		return "hold"
	}
	if !carrierHealthy {
		return "queue_carrier_retry"
	}
	if o.Expedited {
		return "priority_pack"
	}
	return "standard_pack"
}

func (o *Order) RefundPolicy(reason string) string {
	if o.Status == StatusDelivered && reason == "damaged" {
		return "refund_and_replace"
	}
	if o.Status == StatusCancelled {
		return "refund"
	}
	if o.RiskScore > 80 {
		return "manual_review"
	}
	return "store_credit"
}

// CanFulfill reports whether a paid order can ship given current stock.
func (o *Order) CanFulfill(stockAvailable bool) bool {
	if o.Status != StatusPaid {
		return false
	}
	if !stockAvailable {
		return false
	}
	return true
}

func (o *Order) pendingAction() string {
	if o.RiskScore > 70 {
		return "manual_review"
	}
	return "await_payment"
}

func (o *Order) paidAction() string {
	if o.TotalCents > 100000 {
		return "manager_approval"
	}
	if o.Expedited {
		return "schedule_priority_shipment"
	}
	return "schedule_shipment"
}
