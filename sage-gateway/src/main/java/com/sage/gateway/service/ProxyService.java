package com.sage.gateway.service;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.HttpMediaTypeException;
import org.springframework.web.reactive.function.client.WebClient;

import java.util.Enumeration;

@Service
public class ProxyService {

    private final WebClient webClient;

    public ProxyService(WebClient webClient){
        this.webClient = webClient;
    }
    /*
     * The core proxy logic.
     * 1. Prepares the outbound request.
     * 2. Copies all headers from the incoming request (Context Propagation).
     * 3. Sends the body (if any).
     * 4. Waits for the response (Virtual Thread friendly blocking).
     */
    public ResponseEntity<String> forwardRequest(String targetUrl, HttpMethod method, HttpServletRequest request, String body){
        var requestSpec = webClient.method(method).uri(targetUrl);

        Enumeration<String> headerNames = request.getHeaderNames();
        while(headerNames.hasMoreElements()){
            String header = headerNames.nextElement();

            // We SKIP the 'host' header.
            // Why? Because we are sending this to a different host (the backend),
            // and we don't want to confuse it with the Gateway's host address.
            if (!header.equalsIgnoreCase("host")) {
                requestSpec.header(header, request.getHeader(header));
            }
        }

        if (body != null && !body.isEmpty()) {
            requestSpec.bodyValue(body);
        }
        // .retrieve() sends the request.
        // .toEntity(String.class) converts the response to a standard ResponseEntity.
        // .block() waits for the result. (Safe because we are on a Virtual Thread!)
        return requestSpec.retrieve()
                .toEntity(String.class)
                .block();
    }
}
