//! Backend request router: maps a route to an HTTP status, gating private routes on auth.

pub enum Route {
    Health,
    Users,
    Orders,
    Billing,
    Catalog,
    Unknown,
}

pub fn dispatch(route: Route, authenticated: bool, degraded: bool) -> u16 {
    if degraded {
        return degraded_status(route);
    }
    match route {
        Route::Health => 200,
        Route::Users => guard(authenticated),
        Route::Orders => guard(authenticated),
        Route::Billing => guard(authenticated),
        Route::Catalog => 200,
        Route::Unknown => 404,
    }
}

fn guard(authenticated: bool) -> u16 {
    if authenticated {
        200
    } else {
        401
    }
}

fn degraded_status(route: Route) -> u16 {
    match route {
        Route::Health => 200,
        Route::Catalog => 206,
        Route::Users | Route::Orders | Route::Billing => 503,
        Route::Unknown => 404,
    }
}
