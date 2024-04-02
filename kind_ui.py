from flask import Flask, render_template, request, redirect, url_for
import sqlite3
import subprocess
import yaml

app = Flask(__name__)

# Create a SQLite database to store cluster details
def create_database():
    conn = sqlite3.connect('clusters.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS clusters
                 (name TEXT PRIMARY KEY, k8s_version TEXT, num_nodes INTEGER)''')
    conn.commit()
    conn.close()

# Check if a cluster with the same name already exists
def cluster_exists(name):
    conn = sqlite3.connect('clusters.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM clusters WHERE name=?", (name,))
    count = c.fetchone()[0]
    conn.close()
    return count > 0

# Save cluster details to the database
def save_cluster(name, k8s_version, num_nodes):
    conn = sqlite3.connect('clusters.db')
    c = conn.cursor()
    c.execute("INSERT INTO clusters VALUES (?, ?, ?)", (name, k8s_version, num_nodes))
    conn.commit()
    conn.close()

# Generate Kind cluster configuration YAML
def generate_kind_config(name, num_nodes):
    config = {
        "kind": "Cluster",
        "apiVersion": "kind.x-k8s.io/v1alpha4",
        "nodes": [{"role": "control-plane"}] + [{"role": "worker"} for _ in range(num_nodes - 1)]
    }
    with open(f"kind-config-{name}.yaml", "w") as file:
        yaml.dump(config, file)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/list_clusters')
def list_clusters():
    conn = sqlite3.connect('clusters.db')
    c = conn.cursor()
    c.execute("SELECT * FROM clusters")
    db_clusters = c.fetchall()
    conn.close()

    # Get clusters using kind get clusters command
    kind_output = subprocess.check_output(['kind', 'get', 'clusters']).decode('utf-8')
    kind_clusters = kind_output.strip().split('\n') if kind_output.strip() else []

    return render_template('list_clusters.html', db_clusters=db_clusters, kind_clusters=kind_clusters)

@app.route('/create_cluster', methods=['GET', 'POST'])
def create_cluster():
    if request.method == 'POST':
        name = request.form['name']
        k8s_version = request.form['k8s_version']
        num_nodes = int(request.form['num_nodes'])

        if cluster_exists(name):
            error = f"Cluster with name '{name}' already exists."
            return render_template('create_cluster.html', error=error)

        # Generate Kind cluster configuration YAML
        generate_kind_config(name, num_nodes)

        # Create the Kind cluster
        try:
            subprocess.run(['kind', 'create', 'cluster', '--name', name,
                            '--image', f'kindest/node:v{k8s_version}',
                            '--config', f'kind-config-{name}.yaml'])
            save_cluster(name, k8s_version, num_nodes)
            return redirect(url_for('cluster_created', name=name))
        except subprocess.CalledProcessError as e:
            error = f"Error creating cluster: {str(e)}"
            return render_template('create_cluster.html', error=error)

    return render_template('create_cluster.html')

@app.route('/delete_cluster', methods=['POST'])
def delete_cluster():
    name = request.form['name']
    conn = sqlite3.connect('clusters.db')
    c = conn.cursor()
    c.execute("DELETE FROM clusters WHERE name=?", (name,))
    conn.commit()
    conn.close()
    subprocess.run(['kind', 'delete', 'cluster', '--name', name])
    return redirect(url_for('list_clusters'))

@app.route('/cluster_info/<name>')
def cluster_info(name):
    # Get cluster information using kubectl
    try:
        # Change the Kubernetes context to the selected cluster
          # Use the correct context name format
        context_name = f'kind-{name}'
        subprocess.run(['kubectl', 'config', 'use-context', context_name], check=True)

        # Get deployments
        deployments_output = subprocess.check_output(['kubectl', 'get', 'deployments']).decode('utf-8')
        deployments = deployments_output.strip().split('\n') if deployments_output.strip() else []

        # Get pods
        pods_output = subprocess.check_output(['kubectl', 'get', 'pods']).decode('utf-8')
        pods = pods_output.strip().split('\n') if pods_output.strip() else []

        # Get services
        services_output = subprocess.check_output(['kubectl', 'get', 'services']).decode('utf-8')
        services = services_output.strip().split('\n') if services_output.strip() else []

        return render_template('cluster_info.html', name=name, deployments=deployments, pods=pods, services=services)
    except subprocess.CalledProcessError as e:
        error = f"Error getting cluster information: {str(e)}"
        return render_template('cluster_info.html', name=name, error=error)

@app.route('/cluster_created')
def cluster_created():
    name = request.args.get('name')
    return render_template('cluster_created.html', name=name)

if __name__ == '__main__':
    create_database()
    app.run(debug=True)