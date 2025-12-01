package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import com.example.groceryshoppingapp.adapters.SelectCustomerAdapter
import com.example.groceryshoppingapp.databinding.ActivitySelectCustomerBinding
import com.example.groceryshoppingapp.models.AppUser
import com.google.firebase.firestore.ktx.firestore
import com.google.firebase.ktx.Firebase

class ShopOwnerSelectCustomerActivity : AppCompatActivity() {

    private lateinit var binding: ActivitySelectCustomerBinding
    private val customers = mutableListOf<AppUser>()
    private lateinit var adapter: SelectCustomerAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivitySelectCustomerBinding.inflate(layoutInflater)
        setContentView(binding.root)

        adapter = SelectCustomerAdapter(customers) { selected ->
            val result = Intent()
            result.putExtra("customer", selected)
            setResult(RESULT_OK, result)
            finish()
        }

        binding.rvCustomers.layoutManager = LinearLayoutManager(this)
        binding.rvCustomers.adapter = adapter

        binding.btnBack.setOnClickListener { finish() }

        loadCustomers()
    }

    private fun loadCustomers() {
        Firebase.firestore.collection("users")
            .whereEqualTo("role", "customer")
            .get()
            .addOnSuccessListener { snap ->
                customers.clear()
                for (doc in snap.documents) {
                    val u = doc.toObject(AppUser::class.java)
                        ?.copy(id = doc.id)  // ensure id is set
                    if (u != null) customers.add(u)
                }
                adapter.notifyDataSetChanged()
            }
            .addOnFailureListener {
                Toast.makeText(this, "Failed: ${it.message}", Toast.LENGTH_SHORT).show()
            }
    }
}
