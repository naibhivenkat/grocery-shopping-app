//package com.example.groceryshoppingapp.adapters
//
//import android.view.LayoutInflater
//import android.view.ViewGroup
//import androidx.recyclerview.widget.RecyclerView
//import com.example.groceryshoppingapp.databinding.ItemWalletTransactionBinding
//import com.example.groceryshoppingapp.models.WalletTransaction
//
//class WalletTransactionAdapter(private val transactions: List<WalletTransaction>) :
//    RecyclerView.Adapter<WalletTransactionAdapter.ViewHolder>() {
//
//    class ViewHolder(val binding: ItemWalletTransactionBinding) : RecyclerView.ViewHolder(binding.root)
//
//    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
//        val binding = ItemWalletTransactionBinding.inflate(LayoutInflater.from(parent.context), parent, false)
//        return ViewHolder(binding)
//    }
//
//    override fun getItemCount(): Int = transactions.size
//
//    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
//        val tx = transactions[position]
//        holder.binding.tvTransactionType.text = tx.type
//        holder.binding.tvTransactionAmount.text = "₹${tx.amount}"
//        holder.binding.tvOrderId.text = tx.orderId ?: "-"
//        holder.binding.tvDate.text = tx.dateTime
//    }
//}
package com.example.groceryshoppingapp.adapters

import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.databinding.ItemWalletTransactionBinding
import com.example.groceryshoppingapp.models.WalletTransaction

class WalletTransactionAdapter(private val transactions: List<WalletTransaction>) :
    RecyclerView.Adapter<WalletTransactionAdapter.ViewHolder>() {

    class ViewHolder(val binding: ItemWalletTransactionBinding) : RecyclerView.ViewHolder(binding.root)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val binding = ItemWalletTransactionBinding.inflate(LayoutInflater.from(parent.context), parent, false)
        return ViewHolder(binding)
    }

    override fun getItemCount(): Int = transactions.size

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val tx = transactions[position]
        // 🔧 FIX: Use IDs that match item_wallet_transaction.xml
        holder.binding.tvTransactionType.text = tx.type
        holder.binding.tvTransactionAmount.text = "₹${tx.amount}"
        holder.binding.tvTransactionDate.text = tx.dateTime
    }
}
