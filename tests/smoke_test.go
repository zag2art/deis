// +build integration

package tests

import (
	"bytes"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"text/template"

	"github.com/deis/deis/tests/utils"
)

// A test case is a relative directory plus a command that is expected to
// return 0 for success.
// The cmd field is run as an argument to "sh -c", so it can be arbitrarily
// complex.
type deisTest struct {
	dir string
	cmd string
}

// Tests to exercise a basic Deis workflow.
var smokeTests = []deisTest{
	// Generate and activate a new SSH key named "deis".
	{"", `
if [ ! -f {{.AuthKey}} ]; then
  ssh-keygen -q -t rsa -f {{.AuthKey}} -N '' -C deis
fi
ssh-add {{.AuthKey}}
`},
	// Register a "test" Deis user with the CLI, or skip if already registered.
	{"", `
deis register http://deis.{{.Domain}} \
  --username=test \
  --password=asdf1234 \
  --email=test@test.co.nz || true
`},
	// Log in as the "test" user.
	{"", `
deis login http://deis.{{.Domain}} \
  --username=test \
  --password=asdf1234
`},
	// Add the "deis" SSH key, or skip if it's been added already.
	{"", `
deis keys:add {{.AuthKey}}.pub || true
`},
	// Clone the example app git repository locally.
	{"", `
if [ ! -d ./{{.ExampleApp}} ]; then
  git clone https://github.com/deis/{{.ExampleApp}}.git
fi
`},
	// Remove the stale "deis" git remote if it exists.
	{"{{.ExampleApp}}", `
git remote remove deis || true
`},
	// TODO: GH issue about this sleep hack
	// Create an app named "testing".
	{"{{.ExampleApp}}", `
sleep 6 && deis apps:create testing
`},
	// git push the app to Deis
	{"{{.ExampleApp}}", `
git push deis master
`},
	// TODO: GH issue about this sleep hack
	// Test that the app's URL responds with "Powered by Deis".
	{"{{.ExampleApp}}", `
sleep 6 && curl -s http://testing.{{.Domain}} | grep -q 'Powered by Deis' || \
	(curl -v http://testing.{{.Domain}} ; exit 1)
`},
	// Scale the app's web containers up to 3.
	{"{{.ExampleApp}}", `
deis scale web=3 || deis scale cmd=3
`},
	// Test that the app's URL responds with "Powered by Deis".
	{"{{.ExampleApp}}", `
sleep 7 && curl -s http://testing.{{.Domain}} | grep -q 'Powered by Deis' || \
	(curl -v http://testing.{{.Domain}} ; exit 1)
`},
}

// TestSmokeExampleApp updates a Vagrant instance to run Deis with docker
// containers using the current codebase, then registers a user, pushes an
// example app, and looks for "Powered by Deis" in the HTTP response.
func TestSmokeExampleApp(t *testing.T) {
	cfg := utils.GetGlobalConfig()

	for _, tt := range smokeTests {
		runTest(t, &tt, cfg)
	}
}

var wd, _ = os.Getwd()

// Runs a test case and logs the results.
func runTest(t *testing.T, tt *deisTest, cfg *utils.DeisTestConfig) {
	// Fill in the command string template from our test configuration.
	var cmdBuf bytes.Buffer
	tmpl := template.Must(template.New("cmd").Parse(tt.cmd))
	if err := tmpl.Execute(&cmdBuf, cfg); err != nil {
		t.Fatal(err)
	}
	cmdString := cmdBuf.String()
	// Change to the target directory if needed.
	if tt.dir != "" {
		// Fill in the directory template from our test configuration.
		var dirBuf bytes.Buffer
		tmpl := template.Must(template.New("dir").Parse(tt.dir))
		if err := tmpl.Execute(&dirBuf, cfg); err != nil {
			t.Fatal(err)
		}
		dir, _ := filepath.Abs(filepath.Join(wd, dirBuf.String()))
		if err := os.Chdir(dir); err != nil {
			t.Fatal(err)
		}
	}
	// Execute the command and log the input and output on error.
	fmt.Printf("%v ... ", strings.TrimSpace(cmdString))
	cmd := exec.Command("sh", "-c", cmdString)
	if out, err := cmd.Output(); err != nil {
		t.Fatalf("%v\nOutput:\n%v", err, string(out))
	} else {
		fmt.Println("ok")
	}
}
