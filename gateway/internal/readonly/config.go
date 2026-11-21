package readonly

import (
	"fmt"
	"net"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	MSPID, CertPath, KeyPath, TLSCAPath, PeerEndpoint, ServerName string
	Channel, Chaincode, ListenAddress                             string
	EvaluateTimeout                                               time.Duration
}

func LoadConfig(getenv func(string) string) (Config, error) {
	c := Config{MSPID: getenv("DRUNIX_MSP_ID"), CertPath: getenv("DRUNIX_CERT_PATH"),
		KeyPath: getenv("DRUNIX_KEY_PATH"), TLSCAPath: getenv("DRUNIX_TLS_CA_PATH"),
		PeerEndpoint: getenv("DRUNIX_PEER_ENDPOINT"), ServerName: getenv("DRUNIX_TLS_SERVER_NAME"),
		Channel: "mychannel", Chaincode: "basic", ListenAddress: "127.0.0.1:8001", EvaluateTimeout: 5 * time.Second}
	for name, value := range map[string]string{"DRUNIX_MSP_ID": c.MSPID, "DRUNIX_CERT_PATH": c.CertPath,
		"DRUNIX_KEY_PATH": c.KeyPath, "DRUNIX_TLS_CA_PATH": c.TLSCAPath, "DRUNIX_PEER_ENDPOINT": c.PeerEndpoint,
		"DRUNIX_TLS_SERVER_NAME": c.ServerName} {
		if strings.TrimSpace(value) == "" {
			return c, fmt.Errorf("%s is required", name)
		}
	}
	if value := getenv("DRUNIX_CHANNEL"); value != "" && value != c.Channel {
		return c, fmt.Errorf("only channel mychannel is reviewed")
	}
	if value := getenv("DRUNIX_CHAINCODE"); value != "" && value != c.Chaincode {
		return c, fmt.Errorf("only diagnostic chaincode basic is reviewed")
	}
	endpoint := strings.TrimPrefix(c.PeerEndpoint, "dns:///")
	peerHost, peerPort, splitErr := net.SplitHostPort(endpoint)
	peerNumber, portErr := strconv.Atoi(peerPort)
	if splitErr != nil || peerHost == "" || strings.ContainsAny(peerHost, " /\t\n") || portErr != nil || peerNumber < 1 || peerNumber > 65535 {
		return c, fmt.Errorf("DRUNIX_PEER_ENDPOINT must be host:port or dns:///host:port")
	}
	if value := getenv("DRUNIX_LISTEN_ADDRESS"); value != "" {
		c.ListenAddress = value
	}
	host, port, err := net.SplitHostPort(c.ListenAddress)
	portNumber, portErr := strconv.Atoi(port)
	if err != nil || portErr != nil || portNumber < 1 || portNumber > 65535 || net.ParseIP(host) == nil || !net.ParseIP(host).IsLoopback() {
		return c, fmt.Errorf("DRUNIX_LISTEN_ADDRESS must bind a loopback IP")
	}
	if value := getenv("DRUNIX_EVALUATE_TIMEOUT"); value != "" {
		c.EvaluateTimeout, err = time.ParseDuration(value)
		if err != nil || c.EvaluateTimeout < 100*time.Millisecond || c.EvaluateTimeout > 10*time.Second {
			return c, fmt.Errorf("DRUNIX_EVALUATE_TIMEOUT must be between 100ms and 10s")
		}
	}
	return c, nil
}
