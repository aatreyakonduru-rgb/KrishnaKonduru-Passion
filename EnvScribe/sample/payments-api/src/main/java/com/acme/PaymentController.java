package com.acme;
import org.springframework.web.bind.annotation.*;
@RestController
public class PaymentController {
    @Value("${payments.gateway.timeout}")
    private int timeout;
    @PostMapping("/payments")
    public String create() { return jdbc.query("select id, status from payments where id = 1"); }
    @GetMapping("/payments/{id}")
    public String get() { return "ok"; }
    String apiKey = "Zx81QwErTyUiOp09AsDfGhJkLmNb4V";
}
