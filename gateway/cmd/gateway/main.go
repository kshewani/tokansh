package main

import (
	"context"
	"errors"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
	"tokansh/gateway/internal/readonly"
	"tokansh/gateway/internal/registration"
)

func main() {
	c, err := readonly.LoadConfig(os.Getenv)
	if err != nil {
		log.Fatal(err)
	}
	sdk, err := readonly.Connect(c)
	if err != nil {
		log.Fatal(err)
	}
	defer sdk.Close()
	key := registration.Secret(os.Getenv("TOKANSH_GATEWAY_SECRET"))
	operator := registration.Secret(os.Getenv("TOKANSH_OPERATOR_SECRET"))
	var serviceSigner string
	service := &registration.Service{Key: key}
	if len(key) == 32 && len(operator) == 32 {
		adapter, err := registration.NewAdapter(sdk.GatewayClient(), c.MSPID, c.CertPath)
		if err != nil {
			log.Fatal("registration signer configuration failed")
		}
		service.Ledger = adapter
		serviceSigner = adapter.Signer()
	}
	service.Signer = serviceSigner
	mux := http.NewServeMux()
	mux.Handle("/v1/tokansh/", registration.Handler(service, operator))
	mux.Handle("/", readonly.NewHandler(sdk, c))
	server := &http.Server{Addr: c.ListenAddress, Handler: mux, ReadHeaderTimeout: 2 * time.Second,
		ReadTimeout: 3 * time.Second, WriteTimeout: 15 * time.Second, IdleTimeout: 30 * time.Second, MaxHeaderBytes: 8192}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		defer cancel()
		server.Shutdown(shutdown)
	}()
	log.Printf("diagnostics=READ_ONLY registration=AUTH_REQUIRED listen=%s", c.ListenAddress)
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal("private HTTP listener failed")
	}
}
