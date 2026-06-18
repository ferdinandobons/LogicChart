package billing;

/** Settles payments through their lifecycle states. */
public class BillingService {

    public enum PaymentState {
        AUTHORIZED,
        CAPTURED,
        REFUNDED,
        FAILED
    }

    public String settle(PaymentState state, long amountCents) {
        switch (state) {
            case AUTHORIZED:
                return capture(amountCents, false);
            case CAPTURED:
                return "already_settled";
            case REFUNDED:
                return "refunded";
            case FAILED:
                return "retry_payment";
            default:
                return "manual_review";
        }
    }

    public String refund(PaymentState state, boolean customerFault) {
        if (customerFault) {
            return "store_credit";
        }
        switch (state) {
            case CAPTURED:
                return "refund";
            case REFUNDED:
                return "already_refunded";
            case AUTHORIZED:
                return "void_authorization";
            case FAILED:
                return "no_payment";
            default:
                return "manual_review";
        }
    }

    private String capture(long amountCents, boolean highRisk) {
        if (amountCents <= 0) {
            return "invalid_amount";
        }
        if (highRisk || amountCents > 100000) {
            return "review_capture";
        }
        return "captured";
    }
}
