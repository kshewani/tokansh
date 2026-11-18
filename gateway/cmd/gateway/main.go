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
	server := &http.Server{Addr: c.ListenAddress, Handler: readonly.NewHandler(sdk, c), ReadHeaderTimeout: 2 * time.Second,
		ReadTimeout: 3 * time.Second, WriteTimeout: 15 * time.Second, IdleTimeout: 30 * time.Second, MaxHeaderBytes: 8192}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		defer cancel()
		server.Shutdown(shutdown)
	}()
	log.Printf("mode=READ_ONLY listen=%s", c.ListenAddress)
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal("private HTTP listener failed")
	}
}
